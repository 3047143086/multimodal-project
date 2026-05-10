import requests
# import wget, time, json
import time, json

from urllib.parse import urlencode
from urllib.parse import quote
import subprocess, os
import hashlib
import base64
import uuid
# import librosa, soundfile


def dytts_fun(text, timbre, name):  # 倒映有声
    url = "https://tts.daoying.tech/text2audio?"
    # text= "更年轻的身体，容得下更多元的文化、审美和价值观。有一天我终于发现，不只是我们在教你们如何生活，你们也在启发我们怎样去更好的生活。那些抱怨一代不如一代的人，应该看看你们，就像我一样。"
    text = quote(text, encoding="utf-8")
    data = {
        "lan": "zh",
        "spd": 4,
        "ctp": 1,
        "pdt": 172,
        "cuid": "cjs",
        "aue": 6,
        "per": timbre,   # 男：fs_haoran_vc, //  女：fs_zhangyu_cn_en, fs_tangqi_cn_en, fs_lilinrui_vc
        "tex": text
    }
    data = urlencode(data, encoding="utf-8")
    r = requests.post(url, data)

    fp = open(name + '_ori.wav', 'wb')
    fp.write(r.content)
    fp.close()

    # 方法1，多线程速度慢
    # cmd = "ffmpeg -i " + name + '_ori.wav' + " -y -ar 16000 " + name + '.wav'  # ffmpeg -i 输入文件 -ar 采样率  输出文件
    # subprocess.call(cmd, shell=True)

    # 方法2
    # print(librosa.get_samplerate('1_ori.wav'))
    y, sr = librosa.load(name + '_ori.wav', sr=None)
    y_16k = librosa.resample(y, orig_sr=sr, target_sr=16000)
    soundfile.write(name + '.wav', y_16k, 16000)


def GGTTS(text, timbre, name):  # 呱呱有声
    headers = {"Content-Type": "application/json"}
    payload = {"appKey": 'twtc9xJX', "appSecret": '56e2665e9c004386899f37edbe4c6534'}

    r = requests.post('http://120.131.1.135:80/open/auth', data=json.dumps(payload), headers=headers)
    accessToken = json.loads(r.content)['data']['accessToken']

    payload = {
        "accessToken": accessToken,
        "requestId": 'zkwg',
        "text": text,
        "speaker": timbre,  # 女: mina, v_wenbing; 男: subo
        "stretch": 10,  # 以0.1倍为单位的变速系数，整数，默认为10，即1.0倍，范围[5, 30]
        # "gainDeciBel": 0,  # 分贝为单位的音量增益，整数，默认为0，范围[-20, 20]
        # "compDeciBel": 0,  # 分贝为单位的压缩器阈值，整数，默认为0，范围[-20, 0]
        # "limitDeciBel": 0,  # 分贝为单位的限幅器阈值，整数，默认为0，范围[-20, 0]
        # "encoder": 0,  # 音频编码，默认为MP3，取值{0:MP3, 1:OPUS}
        "bitRate": 1,  # 音频编码比特率，默认为32kbps，取值{0:8kbps, 1:16kbps, 2:32kbps}
        # "archiveTimestamp": True,  # 是否返回文本时间戳，默认为否
        # "silenceHeadMs": 500,  # 控制开头静音时长，单位为毫秒，整数，取值范围[0, 5000]，默认采用自动预测的时长
        # "silenceTailMs": 600,  # 控制结尾静音时长，单位为毫秒，整数，取值范围[0, 5000]，默认采用自动预测的时长
    }
    r = requests.post('http://120.131.1.135:80/open/tts', data=json.dumps(payload), headers=headers)

    with open(name + '.wav', 'wb') as fid:
        fid.write(r.content)


def MYTTS(text, timbre, name):  # 魔音
    timestamp = str(int(time.time()))
    # appkey = '31573E98434491E16D9A98C46858480A'
    # message = '+'.join([appkey, 'BE7D91E849EE551E2D797A5639F2122E', timestamp])  # 通用

    appkey = 'ADF425FD3B810FE2CBC187282130F395'
    message = '+'.join([appkey, 'E1EDD8F23DAF2C885B6DB75B249C894D', timestamp])  # 西安
    m = hashlib.md5()
    m.update(message.encode("utf8"))
    signature = m.hexdigest()

    data = {
        'text': text,
        'speaker': timbre,  # 男：moyangang_meet_24k； 女：moxiaozhao_meet_24k, moruiying_meet_24k
        'audio_type': 'wav',
        'speed': 1,  # 0.5-2.0
        'rate': 16000,  # 音频采样率,默认值：无，由speaker指定默认值,可选值：8000/16000/24000
        # 'streaming': True,  # 是否流式输出，默认为false。可以指定为true，打开后ignore_limit 为true且audio_type 不为wav时，接口流式输出
        # 'symbol_sil': 'semi_250,exclamation_300,question_250,comma_200,stop_300,pause_150,colon_200', # 停顿调节需要对appkey授权后才可以使用，授权前传参无效。
        'ignore_limit': True,  # 忽略1000字符长度限制，需要对appkey授权后才可以使用
        'gen_srt': False,  # 是否生成srt字幕文件，默认不开启。如果开启生成字幕，需要额外计费。生成好的srt文件地址将通过response header中的srt_address字段返回。
        'appkey': appkey,
        'timestamp': timestamp,
        'signature': signature
    }
    try:
        headers = {'Content-Type': 'application/json'}
        response = requests.post(url='https://open.mobvoi.com/api/tts/v1', headers=headers, data=json.dumps(data))
        content = response.content

        with open(os.path.join(os.path.dirname(os.path.abspath("__file__")), name + ".wav"), "wb") as f:
            f.write(content)
    except Exception as e:
        print("error: {0}".format(e))


def tts_bytedance(text, voice_type, name):
    # 填写平台申请的appid, access_token以及cluster
    # appid = "1239837138"
    # access_token = "FTRpJF2Gj2OxyM_CehcFNh6dfslbjoPc"

    # appid = "1508205051"
    # access_token = "R-1JusRDs8JlLqTafdnh6mlan-27n7xm"
    # cluster = "volcano_tts"

    appid = "3786856304"  # zhanglu
    access_token = "DbQvJ00xSAhOLVPwPZnHTfFxjoH519-U"
    cluster = "volcano_tts"

    host = "openspeech.bytedance.com"
    api_url = f"https://{host}/api/v1/tts"
    header = {"Authorization": f"Bearer; {access_token}"}

    request_json = {
        "app": {
            "appid": appid,
            "token": "access_token",
            "cluster": cluster
        },
        "user": {
            "uid": "388808087185088"
        },
        "audio": {
            "voice_type": voice_type,
            "encoding": "wav",
            "speed_ratio": 1.0,
            "volume_ratio": 1.0,
            "pitch_ratio": 1.0,
            "rate": 16000,  # 采样率， 默认24000
            # "emotion": "",  # 情感
        },
        "request": {
            "reqid": str(uuid.uuid4()),
            "text": text,
            "text_type": "plain",
            "silence_duration": 225,
            "operation": "query",
            "with_frontend": 1,
            "frontend_type": "unitTson"
        }
    }

    try:
        resp = requests.post(api_url, json.dumps(request_json), headers=header)
        # print(f"resp body: \n{resp.json()}")
        if "data" in resp.json():
            data = resp.json()["data"]
            file_to_save = open(name + ".wav", "wb")
            file_to_save.write(base64.b64decode(data))
    except Exception as e:
        e.with_traceback()


if __name__ == '__main__':
    text = "你好，很高兴见到你。 Hi! Nice to meet you!"
    # text = '北京中科闻歌科技股份有限公司，创立于2017年，定位于认知与决策智能技术型企业。公司基于多模态融合语义分析，聚焦复杂数据解析和AI辅助决策，打造了具有自主知识产权的数据与决策智能基础平台'

    # -----------------------------------倒映
    # audio_path = './'
    # ran_str = 'zky1'
    # dytts_fun(text, audio_path, ran_str)

    # -----------------------------------呱呱
    # timbre = 'mina'  # mina, v_wenxue, v_wenbing, v_linglong2; subo
    # name = 'kl'
    # t00 = time.time()
    # GGTTS(text, timbre, name)
    # print(time.time() - t00)

    # # -----------------------------------魔音
    timbre = 'moruiying_meet_24k'  # 男：moyangang_meet_24k；'liyuansong_meet_24k' 女：moxiaozhao_meet_24k, moruiying_meet_24k
    name = 'moruiying_meet_24k'
    MYTTS(text, timbre, name)