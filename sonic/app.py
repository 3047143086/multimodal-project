import os

os.environ["CUDA_VISIBLE_DEVICES"] = "0"
print("当前可见GPU:", os.environ["CUDA_VISIBLE_DEVICES"])
import random
import string
import time
import traceback
import sys
import urllib
import requests
from flask import Flask, request
from flasgger import Swagger
from urllib.parse import urlparse
from requests_toolbelt import multipart
from urllib.request import urlretrieve
from datetime import datetime
from multiprocessing import Process, Queue
from sonic import Sonic
from tts_utils import MYTTS
from threading import Thread
from urllib.parse import quote

app = Flask(__name__)
Swagger(app)


log_dir = "./logs"
os.makedirs(log_dir, exist_ok=True)

task_queue = Queue(maxsize=0)
task_list = []

print("[INFO] 初始化 Sonic 全局模型...")

global_pipe = Sonic(0)
print("[INFO] Sonic 初始化完成。")


def ensure_dir(path, permission=0o777):
    if not os.path.exists(path):
        print(f"[INFO] 创建目录: {path}")
        os.makedirs(path, exist_ok=True)
    current_permission = os.stat(path).st_mode & 0o777
    if current_permission != permission:
        os.chmod(path, permission)
        print(f"[INFO] 目录权限调整为: {oct(permission)} ({path})")


def download_if_needed(video_url, target_folder):
    parsed_url = urlparse(video_url)
    video_name = os.path.basename(parsed_url.path)
    local_path = os.path.join(target_folder, video_name)

    if os.path.exists(local_path):
        return local_path

    os.makedirs(target_folder, exist_ok=True)

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://qscloudhongqi.wengegroup.com/",
    }

    with requests.get(video_url, stream=True, timeout=15, headers=headers) as r:
        r.raise_for_status()
        with open(local_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

    return local_path


def run_task(
    task_id, callback_url, in_audio, in_images, content_txt, timbre, emotion_path
):
    t0 = time.time()
    try:
        ran_str = "".join(random.sample(string.ascii_letters + string.digits, 8))

        # ---- 音频合成 ---- #
        print("in_audio", in_audio)
        if len(str(in_audio)) > 0 and in_audio is not None:
            if os.path.exists(in_audio):
                audio_path = in_audio
            else:
                audio_path = "./outputs/" + ran_str + ".wav"
                if os.path.exists(audio_path):
                    os.remove(audio_path)

                try:
                    # URL编码处理（保持原有逻辑）
                    if in_audio.startswith(("http://", "https://")):
                        protocol, _, domain, path = in_audio.split("/", 3)
                        encoded_path = quote(path)
                        encoded_url = f"{protocol}//{domain}/{encoded_path}"
                    else:
                        encoded_url = quote(in_audio)

                    print(f"原始URL: {in_audio}")
                    print(f"编码后URL: {encoded_url}")

                    opener = urllib.request.build_opener()
                    ua_list = [
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:102.0) Gecko/20100101 Firefox/102.0",
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.0.0 Safari/537.36",
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.5060.114 Safari/537.36 Edg/103.0.1264.62",
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:98.0) Gecko/20100101 Firefox/98.0",
                        "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/72.0.3626.81 Safari/537.36 SE 2.X MetaSr 1.0",
                    ]
                    opener.addheaders = [("User-Agent", random.choice(ua_list))]
                    urllib.request.install_opener(opener)

                    urlretrieve(encoded_url, audio_path)
                    print("音频下载完成...")

                except urllib.error.URLError as e:
                    print(f"URL访问错误: {e.reason}")
                except urllib.error.HTTPError as e:
                    print(f"HTTP错误: {e.code} - {e.reason}")
                except Exception as e:
                    print(f"下载失败: {str(e)}")

        elif timbre:
            print(
                f"[Task {task_id}] 使用 TTS 合成语音，内容: {content_txt}, 音色: {timbre}"
            )
            MYTTS(content_txt, timbre, f"./outputs/{ran_str}")
            audio_path = f"./outputs/{ran_str}.wav"
        else:
            raise Exception("无效的音频输入")

        print(f"[Task {task_id}] 音频处理完成: {audio_path}")

        # 2. 下载图片
        print(f"[Task {task_id}] 开始下载图片: {in_images}")
        image_local_path = download_if_needed(in_images, f"./outputs/{ran_str}")
        print(f"[Task {task_id}] 图片下载完成: {image_local_path}")

        # 🔥 新增：音频时长判断与截取
        import librosa
        import soundfile as sf

        MAX_SONIC_DURATION = 5.0  # Sonic处理的最大时长（秒）

        # 获取音频时长
        audio, sr = librosa.load(audio_path, sr=None)
        audio_duration = len(audio) / sr
        print(f"[Task {task_id}] 音频时长: {audio_duration:.2f}秒")

        # 决定使用的音频路径
        audio_for_sonic = audio_path
        truncated_audio_path = None

        if audio_duration > MAX_SONIC_DURATION:
            # 截取前5秒
            print(
                f"[Task {task_id}] 音频时长超过{MAX_SONIC_DURATION}秒，截取前{MAX_SONIC_DURATION}秒"
            )
            truncated_audio_path = audio_path.replace(
                ".wav", f"_truncated_{MAX_SONIC_DURATION}s.wav"
            )

            # 截取音频
            audio_16k = librosa.load(audio_path, sr=16000)[0]
            truncated_audio = audio_16k[: int(16000 * MAX_SONIC_DURATION)]
            sf.write(truncated_audio_path, truncated_audio, 16000)

            audio_for_sonic = truncated_audio_path
            print(f"[Task {task_id}] 截取完成: {truncated_audio_path}")

        # 3. 视频处理
        print(f"[Task {task_id}] 初始化 sonic 模型...")
        pipe = global_pipe
        output_path = f"./outputs/{ran_str}.mp4"

        print(f"[Task {task_id}] 开始人脸预处理: {image_local_path}")
        face_info = pipe.preprocess(image_local_path, expand_ratio=0.5)
        print(f"[Task {task_id}] 人脸信息: {face_info}")

        try:
            if face_info["face_num"] == 1:
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                print(f"[Task {task_id}] 开始生成视频，输出路径: {output_path}")

                # 🔥 使用处理后的音频（可能是截取后的）
                video_path = pipe.process(
                    image_local_path,
                    audio_for_sonic,  # 使用处理后的音频
                    output_path,
                    min_resolution=512,
                    inference_steps=25,
                    dynamic_scale=1.0,
                )

                print(f"[Task {task_id}] 视频生成完成: {video_path}")

                # 等待视频文件生成，最多10秒
                for i in range(10):
                    if os.path.exists(video_path):
                        break
                    time.sleep(1)
                else:
                    raise FileNotFoundError(f"视频文件生成超时: {video_path}")

                # 调用 process_task 上传视频
                print(f"[Task {task_id}] 开始上传视频...")
                result_sonic = process_task(task_id, callback_url, video_path, t0)
                print(f"[Task {task_id}] 视频上传任务提交完成")

                # 🔥 清理临时截取的音频文件
                if truncated_audio_path and os.path.exists(truncated_audio_path):
                    os.remove(truncated_audio_path)
                    print(f"[Task {task_id}] 清理临时音频: {truncated_audio_path}")

                # 🔥 关键：调用HeyGem时传入原始音频URL
                print(f"======heygem合成中=======")
                requset_heygem(task_id, result_sonic, in_audio, callback_url)

            elif face_info["face_num"] == 0:
                res = {
                    "id": task_id,
                    "data3": "",
                    "code": 501,
                    "msg": "图片中未检测到有效人脸",
                    "progress": 100,
                    "time": time.time() - t0,
                }
                requests.post(
                    url=callback_url,
                    json=res,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 6.1; rv:2.0.1) Gecko/20100101 Firefox/4.0.1"
                    },
                )
                print("res", res)
                raise ValueError(f"[Task {task_id}] 没检测到有效人脸")

            elif face_info["face_num"] >= 2:
                res = {
                    "id": task_id,
                    "data3": "",
                    "code": 502,
                    "msg": "图片中存在多张人脸",
                    "progress": 100,
                    "time": time.time() - t0,
                }
                requests.post(
                    url=callback_url,
                    json=res,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 6.1; rv:2.0.1) Gecko/20100101 Firefox/4.0.1"
                    },
                )
                print("res", res)
                raise ValueError(f"[Task {task_id}] 检测到多人脸")

        except ValueError as ve:
            print(ve)

    except Exception as e:
        print(f"[Task {task_id}] 任务执行出错:")
        res = {
            "id": task_id,
            "data3": "",
            "code": 500,
            "msg": "fail",
            "progress": 100,
            "time": time.time() - t0,
        }
        requests.post(
            url=callback_url,
            json=res,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 6.1; rv:2.0.1) Gecko/20100101 Firefox/4.0.1"
            },
        )
        print("res", res)
        print(traceback.format_exc())


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
                    fields={
                        "files": (
                            os.path.basename(file_path),
                            open(file_path, "rb"),
                            "multipart/form-data",
                        )
                    }
                )

                r = requests.post(
                    url=url,
                    data=data,
                    headers={
                        "STORE_BUCKET_KEY": bucket_key,
                        "Content-Type": data.content_type,
                        "User-Agent": "Mozilla/5.0",
                    },
                    timeout=60,
                )
                print("[DEBUG] 上传响应状态码:", r.status_code)
                print("[DEBUG] 上传响应内容:", r.text)

                result = r.json()["data"][0]

                # res = {
                #     "id": task_id,
                #     "data3": result,
                #     "code": 200,
                #     "msg": "success",
                #     "progress": 100,
                #     "time": time.time() - t0
                # }
                post_status = True

            except Exception:
                res = {
                    "id": task_id,
                    "data3": "",
                    "code": 500,
                    "msg": "fail",
                    "progress": 100,
                    "time": time.time() - t0,
                }
                requests.post(
                    url=callback_url,
                    json=res,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 6.1; rv:2.0.1) Gecko/20100101 Firefox/4.0.1"
                    },
                )
        # requests.post(url=callback_url, json=res, headers={"User-Agent": "Mozilla/5.0 (Windows NT 6.1; rv:2.0.1) Gecko/20100101 Firefox/4.0.1"})
        # print('res', res)

    except Exception as e:
        print(traceback.extract_tb(sys.exc_info()[-1]))
        print(e)
        res = {
            "id": task_id,
            "data3": "",
            "thumbnail": "",
            "code": 500,
            "msg": "fail",
            "progress": 100,
            "time": time.time() - t0,
        }
        with open("logs/logs.txt", "a") as f:
            f.write(
                "error:" + str(traceback.extract_tb(sys.exc_info()[-1])) + str(e) + "\n"
            )

    # logs_output = [datetime.now().strftime('%Y-%m-%d %H:%M:%S'), task_id]
    # with open('logs/logs.txt', 'a') as f:
    #     f.write('outputs:' + str(logs_output) + str(res) + '\n')

    return result


def requset_heygem(task_id, result, in_audio, callback_url):
    import requests

    data = {
        "id": task_id,
        "callback": callback_url,
        "data_url": result,  # 主视频
        "audio_url": in_audio,
    }

    # 设置请求头
    headers = {
        "x-app-key": "6890116ce675486cad6ed65287d7d435",
        "Content-Type": "application/json",
    }

    minio_endpoint = os.environ.get("HEYGEM_URL", "http://10.20.4.7:12021/analysis")
    response = requests.post(
        url=minio_endpoint,
        json=data,  # 自动将data转换为JSON并设置Content-Type
        headers=headers,  # 添加自定义请求头
    )

    print("状态码:", response.status_code)
    try:
        print("响应内容:", response.json())
    except Exception:
        print("原始响应（非 JSON）:", response.text)


@app.route("/analysis", methods=["POST", "GET"])
def main():
    if request.method == "GET":
        return {"code": 200, "msg": "success"}, 200
    try:
        callback_url = request.json.get("callback")  #
        task_id = request.json.get("id")
        in_images = request.json.get("data_url")
        in_audio = request.json.get("audio_url")
        content_txt = request.json.get("content", "")
        timbre = request.json.get("tts", "")
        emotion_path = request.json.get("emotion_path")

    except:
        callback_url = request.form.get("callback")
        task_id = request.form.get("id")
        in_images = request.form.get("data_url")
        in_audio = request.form.get("audio_url")
        content_txt = request.form.get("content", "")
        timbre = request.form.get("tts")
        emotion_path = request.form.get("emotion_path")

    if in_images == None:
        in_images = []
    if in_audio == None:
        in_audio = []

    task_queue.put(
        [task_id, callback_url, in_audio, in_images, content_txt, timbre, emotion_path]
    )
    task_list.append(task_id)
    success_back_json = {
        "code": 200,
        "msg": "SUCCESS",
        "data": {"method": 5, "task_list": task_list},
    }
    logs_input = [
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        task_id,
        callback_url,
        in_audio,
        in_images,
        content_txt,
        timbre,
        emotion_path,
    ]
    print("inputs:", logs_input)
    with open("logs/logs.txt", "a") as f:
        f.write("inputs:" + str(logs_input) + "\n")
    return success_back_json


def Task_Process():
    while True:
        try:
            args = task_queue.get()
            print(f"[Listener] Got task {args[0]}, starting process...")
            t = Thread(target=run_task, args=args)
            t.start()
            t.join()
            if task_list:
                task_list.pop(0)
            print(f"[Listener] Task {args[0]} done")
        except Exception as e:
            print(traceback.format_exc())


listener_thread = Thread(target=Task_Process, daemon=True)
listener_thread.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8089, debug=False)
