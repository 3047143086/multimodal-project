from flask import Flask, request, jsonify, send_file
from werkzeug.utils import secure_filename
import os
from runpdf2zh import main as pdf2zh_main

app = Flask(__name__)

# 设置上传文件的保存路径
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

@app.route('/translate', methods=['POST'])
def translate_pdf():

    # 检查 request.files 中是否存在键 'file'
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400

    files = request.files.getlist('file')
    if not files:
        return jsonify({"error": "No selected file"}), 400

    file_paths = []
    results = []

    for file in files:
        if file.filename == '':
            continue  # 跳过空文件

        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        file_paths.append(file_path)

    # 调用 pdf2zh 的 main 函数进行翻译
    args = [
        *file_paths,
        "--output", app.config['UPLOAD_FOLDER'],
        "--lang-in", request.form.get("lang_in", "en"),
        "--lang-out", request.form.get("lang_out", "zh"),
        "--service", request.form.get("service", "bing"),
        "--thread", request.form.get("thread", "4"),
    ]
    # --- 新增 ignore_cache 逻辑 ---
    # 检查前端是否传了 ignore_cache，如果是 "true" 则加入参数
    ignore_cache = request.form.get("ignore_cache", "false").lower() == "true"
    if ignore_cache:
        args.append("--ignore-cache")
    # ----------------------------        
    pages = request.form.get("pages", "").strip()
    if pages:
        args.append("--pages")
        args.append(pages)
    pdf2zh_main(args)

    for file_path in file_paths:
        filename = os.path.basename(file_path)
        mono_file = os.path.join(app.config['UPLOAD_FOLDER'], f"{os.path.splitext(filename)[0]}-mono.pdf")
        dual_file = os.path.join(app.config['UPLOAD_FOLDER'], f"{os.path.splitext(filename)[0]}-dual.pdf")

        results.append({
            "original_file": file_path,
            "mono_file": mono_file,
            "dual_file": dual_file
        })
    return jsonify(results), 200

@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    # 发送文件到前端
    return send_file(os.path.join(app.config['UPLOAD_FOLDER'], filename), as_attachment=True)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
