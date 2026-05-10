from flask import Flask, request, jsonify, send_file
from werkzeug.utils import secure_filename
import os
from runpdf2zh import main as pdf2zh_main
from utils import save_file, delete_file_by_path, request_api
from minio_proccess import upload_file_with_presigned_url, download_minio_file, get_filename_from_url_simple
import time
import yaml
import json
from threading import Thread
import traceback
with open('/app/pdf2zh/config.yaml', 'r', encoding='utf-8') as f:
    config = yaml.load(f.read(), Loader=yaml.FullLoader)
    
app = Flask(__name__)

# 设置上传文件的保存路径
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def run_task(args, file_paths, jobId):    
    try:
        pdf2zh_main(args)
        for file_path in file_paths:
            filename = os.path.basename(file_path)
            mono_file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{os.path.splitext(filename)[0]}-mono.pdf")
            dual_file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{os.path.splitext(filename)[0]}-dual.pdf")
            # results.append({
            #     "original_file": file_path,
            #     "mono_file": mono_file,
            #     "dual_file": dual_file
            # })
            # print(mono_file_path)
            if os.path.exists(mono_file_path):
                # print(f"文件 {file_path} 存在")
                # 获取minio预上传url
                get_upload_url = config["get_upload_url"]
                request_body = {
                    "businessType": "translate-result",  # 业务类型：fileupload/translate-result
                    "uuid": jobId,       # 业务UUID（如任务ID）
                    "fileName": f"{os.path.splitext(filename)[0]}-mono.pdf"    # 文件名
                }
                res = request_api(get_upload_url, request_body)
                if res is not None:
                    objectKey, uploadUrl = res["data"]["objectKey"],  res["data"]["uploadUrl"]
                    # 上传翻译后的文件
                    upload_res = upload_file_with_presigned_url(uploadUrl, mono_file_path)
            else:
                upload_res = False

            if upload_res:
                request_body = {
                    "jobId": jobId,  # 业务UUID（如任务ID）
                    "status": 0,       # 任务状态:0成功，9失败
                    "objectKey": objectKey    # Minl0对象Key(status=0时必填)
                }
            else:
                request_body = {
                    "jobId": jobId,  # 业务UUID（如任务ID）
                    "status": 9,       # 任务状态:0成功，9失败
                    "objectKey": objectKey,    # 文件名
                    "errorlessage": "上传翻译文件失败！！"
                } 
            # 文档翻译结束回调
            finish_api = config["finish_api"] 
            res = request_api(finish_api, request_body)

            # 注释掉删除文件的代码，保留翻译后的结果
            # delete_file_by_path(file_path)
            # delete_file_by_path(mono_file_path)
            # delete_file_by_path(dual_file_path)
    except Exception as e:
        print(traceback.print_exc()) 
        finish_api = config["finish_api"]   
        errorlessage = "翻译或保存过程报错！！"
        request_body = {
                "jobId": jobId,  # 业务UUID（如任务ID）
                "status": 9,       # 任务状态:0成功，9失败
                "objectKey": "",    # 文件名
                "errorlessage": errorlessage
            }
        res = request_api(finish_api, request_body) 
     

@app.route('/translate', methods=['POST', "GET"])
def translate_pdf():

    if request.method == "GET":
        return {"code": 200, "msg": "success"}, 200
    
    start = time.time()
    try:
        jobId = request.json.get('jobId')
        file_url = request.json.get('file_url')
        lang_in = request.json.get('lang_in')
        lang_out = request.json.get('lang_out',"zh")
        termbase_id = request.json.get('termbase_id', None) # 术语库id
        
        service = request.json.get('service', "yi_wenge")
        thread = request.json.get('thread', "4")
        ignore_cache = request.json.get('ignore_cache', "false").lower() == "true"
        pages = request.json.get('pages', "").strip() # "1-3"
    except:
        jobId = request.form['jobId']
        file_url = request.form['file_url']
        lang_in = request.form['lang_in']
        lang_out = request.form['lang_out']
        termbase_id = request.form.get("termbase_id", None)

        service = request.form.get("service", "yi_wenge")
        thread = request.form.get("thread", "4")
        ignore_cache = request.form.get("ignore_cache", "false").lower() == "true"
        pages = request.form.get("pages", "").strip()

    file_paths = []
    results = {}
    message = None
    try:
        filename = get_filename_from_url_simple(file_url)
        file_save_path = os.path.join(UPLOAD_FOLDER, filename)
        file_save_res = download_minio_file(file_url, file_save_path)
        # file_save_path = save_file(file_url, UPLOAD_FOLDER)

        if not file_save_res:
            message = "保存文件url失败！！"
            assert 1==2, message
            # return jsonify({"error": "Failed to save file"}), 501

        file_paths.append(file_save_path)

        # 调用 pdf2zh 的 main 函数进行翻译
        args = [
            *file_paths,
            "--output", app.config['UPLOAD_FOLDER'],
            "--lang-in", lang_in,
            "--lang-out", lang_out,
            "--service", service,
            "--thread", thread,
            "--onnx", "/app/pdf2zh/model/doclayout_yolo_docstructbench_imgsz1024.onnx",
            "--task_id", jobId,
            "--termbase_id", termbase_id
        ]
        # --- 新增 ignore_cache 逻辑 ---
        # 检查前端是否传了 ignore_cache，如果是 "true" 则加入参数
        if ignore_cache:
            args.append("--ignore-cache")

        # ----------------------------        
        if pages:
            args.append("--pages")
            args.append(pages)
        
        t= Thread(target=run_task, args=(args, file_paths, jobId))
        # return "Receive successful!",200
        t.start()

    except Exception as e:
        print(traceback.print_exc()) 
        finish_api = config["finish_api"]      
        if message is not None:
            errorlessage = message
        else:
            errorlessage = "未知错误服务报错！！"
        request_body = {
                "jobId": jobId,  # 业务UUID（如任务ID）
                "status": 9,       # 任务状态:0成功，9失败
                "objectKey": "",    # 文件名
                "errorlessage": errorlessage
            }
        res = request_api(finish_api, request_body)  

    elapsed = time.time()-start
    elapsed = f'{round(elapsed, 5)}s'
    msg = "Success!"
    results = json.dumps({"code": 200, "msg": msg, "data": [], "time": elapsed}, ensure_ascii=False)
    return results

@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    # 发送文件到前端
    return send_file(os.path.join(app.config['UPLOAD_FOLDER'], filename), as_attachment=True)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
