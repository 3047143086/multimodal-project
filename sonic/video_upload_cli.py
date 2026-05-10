import os
import requests
from requests_toolbelt import multipart
import time
import traceback
from datetime import datetime

def upload_video(
    video_path: str,
    upload_url: str = "http://hongqiplus.wengegroup.com/mam/api/file/getUrl",
    bucket_key: str = "zs-a3efde7e",
    max_retries: int = 3,
    timeout: int = 60
) -> dict:
    """
    简化版视频上传函数
    :param video_path: 要上传的视频绝对路径（如 "/u01/.../数字人1.mp4"）
    :param upload_url: 服务器接收接口URL
    :param bucket_key: 存储桶标识
    :param max_retries: 最大重试次数
    :param timeout: 单次请求超时时间(秒)
    :return: 包含上传结果的字典
    """
    # 1. 验证文件是否存在
    if not os.path.isfile(video_path):
        return {
            "status": "error",
            "message": f"视频文件不存在: {video_path}",
            "timestamp": datetime.now().isoformat()
        }

    # 2. 准备上传数据
    file_name = os.path.basename(video_path)
    headers = {
        "STORE_BUCKET_KEY": bucket_key,
        "User-Agent": "Mozilla/5.0 (Windows NT 6.1; rv:2.0.1) Gecko/20100101 Firefox/4.0.1"
    }

    # 3. 带重试机制的上传
    for attempt in range(max_retries):
        try:
            with open(video_path, 'rb') as f:
                # 使用流式上传避免内存问题
                data = multipart.MultipartEncoder(
                    fields={'files': (file_name, f, 'video/mp4')}
                )
                headers["Content-Type"] = data.content_type

                response = requests.post(
                    upload_url,
                    data=data,
                    headers=headers,
                    timeout=timeout
                )
                response.raise_for_status()

                # 返回成功结果
                return {
                    "status": "success",
                    "file_url": response.json().get("data", [""])[0],
                    "file_name": file_name,
                    "attempts": attempt + 1,
                    "timestamp": datetime.now().isoformat()
                }

        except Exception as e:
            last_error = str(e)
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # 指数退避等待
                continue
            
            return {
                "status": "error",
                "error": last_error,
                "file_name": file_name,
                "attempts": attempt + 1,
                "timestamp": datetime.now().isoformat()
            }

def simple_upload_task(
    video_path: str,
    callback_url: str = None,
    task_id: str = None
) -> dict:
    """
    完整上传任务处理
    :param video_path: 要上传的视频绝对路径
    :param callback_url: 可选的回调通知地址
    :param task_id: 可选的任务ID
    :return: 上传结果字典
    """
    start_time = time.time()
    result = {
        "task_id": task_id or "N/A",
        "start_time": datetime.fromtimestamp(start_time).isoformat()
    }

    # 执行上传
    upload_result = upload_video(video_path)
    result.update(upload_result)
    result["elapsed_seconds"] = round(time.time() - start_time, 2)

    # 可选回调
    if callback_url:
        try:
            requests.post(callback_url, json=result, timeout=5)
        except Exception as e:
            result["callback_error"] = str(e)

    # 打印简明日志
    log_msg = f"[{result['timestamp']}] {result['status'].upper()}: {result['file_name']}"
    if result["status"] == "success":
        log_msg += f" → {result['file_url']}"
    else:
        log_msg += f" | ERROR: {result.get('error', 'unknown')}"
    
    print(log_msg)
    return result

# 使用示例 ---------------------------------------------------
if __name__ == "__main__":
    # 直接上传视频（替换为您的实际路径）
    upload_result = simple_upload_task(
        video_path="/u01/liushiguo/lsg/Sonic/examples/image/wanglei.png",
        callback_url="http://hongqi.wengegroup.com/artificial_intelligence_synthesis/api/task/callback",  # 可选
        task_id="task_123"  # 可选
    )
    
    print("最终上传结果:", upload_result)
