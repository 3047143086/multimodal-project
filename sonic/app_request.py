import requests

api_url = "http://10.20.4.7:38439/analysis"
# api_url = "http://10.20.4.7:25335/analysis"
# api_url = "http://10.20.4.7:8080/analysis"



# 构造参数
payload = {
    "id": "138s",  # 任务唯一 ID
    "callback": "http://hongqi.wengegroup.com/artificial_intelligence_synthesis/api/task/callback",  # 回调接口，用于接收结果通知
    "data_url": "https://source.wengegroup.com/mam2/683fa559e4b0e9d2bb0ff31f.png",
    #   https://source.wengegroup.com/mam2/683e9b72e4b0e9d2bb0fe085.png  # duornelian
    #   https://source.wengegroup.com/mam2/683e9c98e4b0e9d2bb0fe08f.png  # wurenlian
    #   https://source.wengegroup.com/mam2/683ebb7fe4b0e9d2bb0fe2b2.png  # nazha
    #   https://source.wengegroup.com/mam2/683fa559e4b0e9d2bb0ff31f.png  # nazha300
    #   https://source.wengegroup.com/mam2/6848f720e4b0e9d2bb102f6a.jpg  # nvzhubo
    # https://source.wengegroup.com/mam2/68491d99e4b0e9d2bb1030c4.png

    "audio_url": "https://source.wengegroup.com/mam2/684955cde4b0e9d2bb10341f.wav", 
    # "audio_url": "https://source.wengegroup.com/mam2/682c4cdee4b0e9d2bb0f91d4.wav", 
    # https://source.wengegroup.com/mam2/682c4cdee4b0e9d2bb0f91d4.wav
}

# 发送 POST 请求
try:
    response = requests.post(api_url, json=payload, timeout=60)
    print("请求响应状态:", response.status_code)
    print("返回数据:", response.json())
except Exception as e:
    print("请求失败:", e)
