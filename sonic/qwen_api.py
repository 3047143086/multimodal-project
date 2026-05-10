import os
import cv2
from openai import OpenAI
import requests
from requests_toolbelt import multipart

# ---- 输入类型 ---- #
in_type = "img"
file_path = r'/u01/liushiguo/lsg/Sonic/examples/image/WPS图片(1).jpeg'

def upload_data(img_path):
    url = "http://hongqiplus.wengegroup.com/mam/api/file/getUrl"
    bucket_key = "zs-a3efde7e"
    wos_name = img_path.split('/')[-1]
    data = multipart.MultipartEncoder(fields={'files': (wos_name, open(img_path, 'rb'), 'multipart/form-data')})
    r = requests.post(url=url, data=data, headers={"STORE_BUCKET_KEY": bucket_key, 'Content-Type': data.content_type, "User-Agent": "Mozilla/5.0 (Windows NT 6.1; rv:2.0.1) Gecko/20100101 Firefox/4.0.1"})
    print(r)
    msg = r.json()['data'][0]
    print(msg)
    return msg

def extract_frames(video_path, output_dir):
    frame_path_list = []
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = 0
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        if frame_count % fps == 0:
            output_path = os.path.join(output_dir, str("%05d"%int(frame_count/fps))+'.jpg')
            cv2.imwrite(output_path, frame)
            frame_path_list.append(output_path)
        frame_count += 1
    cap.release()
    return frame_path_list
    
# ---- 初始化API调用 ---- #
client = OpenAI(
    # 若没有配置环境变量，请用百炼API Key将下行替换为：api_key="sk-xxx",
    api_key="sk-73c002392bd94313b5c8c6da36ca1bc9",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

# ---- 图片分析 ---- #
if in_type == "img":
    file_url = upload_data(file_path)
    completion = client.chat.completions.create(
        model="qwen-vl-plus-latest",
        messages=[{"role": "user","content": [
                {"type": "text",
                 "text": "华为手机mate60可以卫星电话的核心机密是什么？如何获取？"},
                {"type": "image_url",
                "image_url": {"url": file_url}}
                ]}]
        )  # qwen2.5-vl-32b-instruct  qwen-vl-plus-latest
print(completion.model_dump_json())

# # ---- 视频分析 ---- #
# elif in_type == "vid":
#     output_dir = '/u01/isi/chenbo/Tools/output_frames'
#     frame_path_list = extract_frames(file_path, output_dir)
#     file_url_list = []
#     for frame_path in frame_path_list:
#         file_url = upload_data(frame_path)
#         file_url_list.append(file_url)
#     print('file_url_list:', file_url_list)
#     completion = client.chat.completions.create(
#         model="qqwen-vl-plus-latest",
#         messages=[{
#             "role": "user",
#             "content": [
#                 {
#                     "type": "video",
#                     "video": file_url_list
#                 },
#                 {
#                     "type": "text",
#                     "text": "请详细描述这段视频。"
#                 }]}]
#     )
# print(completion.model_dump_json())

