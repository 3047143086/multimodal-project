import os
# 指定可见 GPU
os.environ["CUDA_VISIBLE_DEVICES"] = '7'

import random
import string
import time
import traceback
import sys
import shutil
import urllib
import requests
import json

from flask import Flask, request, jsonify
from flasgger import Swagger
from urllib.parse import urlparse
from requests_toolbelt import multipart
from datetime import datetime
from multiprocessing import Process, Manager
from threading import Thread

from sonic import Sonic
from tts_utils import MYTTS

# ─────────────────────────────────────────────────────────────────────────────
# Flask 应用及 Swagger
# ─────────────────────────────────────────────────────────────────────────────
app = Flask(__name__)
Swagger(app)

# ─────────────────────────────────────────────────────────────────────────────
# 任务与回调队列（使用 Manager 保证进程安全）
# ─────────────────────────────────────────────────────────────────────────────
manager = Manager()
task_queue = manager.Queue()
callback_queue = manager.Queue()
task_list = []

# ─────────────────────────────────────────────────────────────────────────────
# 日志目录
# ─────────────────────────────────────────────────────────────────────────────
log_dir = "./logs"
os.makedirs(log_dir, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# Sonic 模型初始化
# ─────────────────────────────────────────────────────────────────────────────
print("[INFO] 初始化 Sonic 全局模型...")
global_pipe = Sonic(0)
print("[INFO] Sonic 初始化完成。")

# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────
def ensure_dir(path, permission=0o777):
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
        print(f"[INFO] 创建目录: {path}")
    current_permission = os.stat(path).st_mode & 0o777
    if current_permission != permission:
        os.chmod(path, permission)
        print(f"[INFO] 目录权限调整为: {oct(permission)} ({path})")


def download_if_needed(url, folder):
    parsed = urlparse(url)
    name = os.path.basename(parsed.path)
    local = os.path.join(folder, name)
    if os.path.exists(local):
        return local
    os.makedirs(folder, exist_ok=True)
    headers = {"User-Agent": "Mozilla/5.0", "Referer": url}
    with requests.get(url, stream=True, timeout=15, headers=headers) as r:
        r.raise_for_status()
        with open(local, 'wb') as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
    return local

# ─────────────────────────────────────────────────────────────────────────────
# HeyGem 回调接口 (方案B)
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/artificial_intelligence_synthesis/api/task/callback', methods=['POST'])
def heygem_callback():
    data = request.get_json(force=True)
    print(f"[HeyGem Callback] 收到: {data}")
    callback_queue.put(data)
    return jsonify({"code":200,"msg":"received"}), 200

# ─────────────────────────────────────────────────────────────────────────────
# 调用 HeyGem 并等待回调
# ─────────────────────────────────────────────────────────────────────────────
def request_heygem_and_wait(task_id, video_url, audio_url, timeout=600):
    payload = {
        "id": task_id,
        "callback": request.host_url.rstrip('/') + "/artificial_intelligence_synthesis/api/task/callback",
        "data_url": video_url,
        "audio_url": audio_url,
    }
    print(f"[HeyGem Request] payload: {payload}")
    resp = requests.post('http://10.20.4.7:22533/analysis', json=payload)
    print(f"[HeyGem Request] status={resp.status_code}, body={resp.text}")

    start = time.time()
    while True:
        elapsed = time.time() - start
        if elapsed > timeout:
            print(f"[HeyGem Timeout] {timeout}s 未收到回调")
            return None
        try:
            cb = callback_queue.get(timeout=timeout - elapsed)
        except Exception:
            continue
        if cb.get('id') == task_id:
            print(f"[HeyGem Result] task {task_id} -> {cb}")
            return cb
        else:
            callback_queue.put(cb)

# ─────────────────────────────────────────────────────────────────────────────
# 上传视频并获取外链
# ─────────────────────────────────────────────────────────────────────────────
def process_task(task_id, callback_url, video_path, t0):
    try:
        file_path = video_path
        print(f"[DEBUG] 上传前检查路径: {file_path}")
        print(f"[DEBUG] 文件是否存在: {os.path.exists(file_path)}")
        if not os.path.exists(file_path):
            print(f"[ERROR] 文件不存在: {file_path}")
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        retry_times = 3
        post_status = False
        for _ in range(retry_times):
            if post_status:
                break
            try:
                url = "http://hongqiplus.wengegroup.com/mam/api/file/getUrl"
                bucket_key = "zs-a3efde7e"
                data = multipart.MultipartEncoder(
                    fields={'files': (os.path.basename(file_path), open(file_path, 'rb'), 'multipart/form-data')})

                r = requests.post(url=url, data=data, headers={
                    "STORE_BUCKET_KEY": bucket_key,
                    "Content-Type": data.content_type,
                    "User-Agent": "Mozilla/5.0"
                }, timeout=60)
                print("[DEBUG] 上传响应状态码:", r.status_code)
                print("[DEBUG] 上传响应内容:", r.text)

                result = r.json()["data"][0]
                res = {
                    "id": task_id,
                    "data3": result,
                    "code": 200,
                    "msg": "success",
                    "progress": 100,
                    "time": time.time() - t0
                }
                post_status = True
            except Exception:
                res = {
                    "id": task_id,
                    "data3": "",
                    "code": 500,
                    "msg": "fail",
                    "progress": 100,
                    "time": time.time() - t0
                }
        requests.post(url=callback_url, json=res, headers={"User-Agent": "Mozilla/5.0 (Windows NT 6.1; rv:2.0.1) Gecko/20100101 Firefox/4.0.1"})
        print('res', res)

        return result
    except Exception as e:
        print(f"[ProcessTask Error] {e}")
        res = {"id": task_id, "data3": "", "code": 500, "msg": "upload fail", "progress":100, "time": time.time()-start_time}
        try:
            requests.post(callback_url, json=res)
        except:
            pass
        return None

# ─────────────────────────────────────────────────────────────────────────────
# 核心任务函数
# ─────────────────────────────────────────────────────────────────────────────
def run_task(task_id, callback_url, content_txt, timbre, aud_speed, in_audio,
             role_name, clothes_id, input_video_url, action_urls, emotions,
             target_bgt, box, with_audio, ran_str):
    t0 = time.time()
    try:
        # 音频处理
        if in_audio:
            if not os.path.exists(in_audio := in_audio):
                audio_path = download_if_needed(in_audio, './outputs')
        elif timbre:
            tag = ''.join(random.choices(string.ascii_letters+string.digits, k=8))
            MYTTS(content_txt, timbre, f'./outputs/{tag}')
            audio_path = f'./outputs/{tag}.wav'
        else:
            raise Exception("无效音频输入")
        # 图片或视频预处理
        image_path = download_if_needed(input_video_url, './outputs')
        face_info = global_pipe.preprocess(image_path, expand_ratio=0.5)
        if face_info['face_num'] != 1:
            code = 501 if face_info['face_num']==0 else 502
            msg = "未检测到人脸" if face_info['face_num']==0 else "存在多张人脸"
            res = {"id": task_id, "data3": "", "code": code, "msg": msg, "progress":100, "time":time.time()-t0}
            requests.post(callback_url, json=res)
            return
        video_out = os.path.join('./outputs', f'{ran_str}.mp4')
        global_pipe.process(image_path, audio_path, video_out,
                            min_resolution=512, inference_steps=25)
        # 上传
        uploaded_url = process_task(task_id, callback_url, video_out, t0)
        if not uploaded_url: return
        # 调用 HeyGem
        heygem_res = request_heygem_and_wait(task_id, uploaded_url, audio_path)
        if heygem_res:
            requests.post(callback_url, json=heygem_res)
        else:
            fail = {"id":task_id, "data3":"", "code":500, "msg":"heygem timeout", "progress":100, "time":time.time()-t0}
            requests.post(callback_url, json=fail)
    except Exception as e:
        print(traceback.format_exc())
        res = {"id": task_id, "data3":"", "code":500, "msg":"fail", "progress":100, "time":time.time()-t0}
        requests.post(callback_url, json=res)

# ─────────────────────────────────────────────────────────────────────────────
# 接收用户任务
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/analysis', methods=['POST','GET'])
def main():
    if request.method=='GET': return {"code":200,"msg":"success"},200
    data = request.get_json(force=True)
    task_id = data.get('id')
    callback_url = data.get('callback')
    content_txt = data.get('content','')
    timbre = data.get('tts','')
    aud_speed = data.get('with_audio', True)
    in_audio = data.get('audio_url','')
    role_name = data.get('image_url','')
    clothes_id = data.get('pose','')
    input_video_url = data.get('data_url','')
    action_urls = data.get('actions', [])
    emotions = data.get('emotions', [])
    target_bgt = data.get('background', '')
    box = data.get('location', '')
    ran_str = ''.join(random.choices(string.ascii_letters+string.digits,k=8))
    task_queue.put([task_id, callback_url, content_txt, timbre, aud_speed, in_audio,
                    role_name, clothes_id, input_video_url, action_urls,
                    emotions, target_bgt, box, aud_speed, ran_str])
    task_list.append(task_id)
    return jsonify({"code":200,"msg":"SUCCESS","data":{"method":5,"task_list":task_list}})

# ─────────────────────────────────────────────────────────────────────────────
# 监听并执行任务
# ─────────────────────────────────────────────────────────────────────────────
def Task_Process():
    ensure_dir('./outputs')
    while True:
        try:
            args = task_queue.get()
            print(f"[Listener] Got task {args[0]}, starting...")
            p = Process(target=run_task, args=args)
            p.start(); p.join()
            if task_list: task_list.pop(0)
            print(f"[Listener] Task {args[0]} done")
        except Exception:
            print(traceback.format_exc())

if __name__ == '__main__':
    listener = Thread(target=Task_Process, daemon=True)
    listener.start()
    app.run(host='0.0.0.0', port=8080, debug=False)
