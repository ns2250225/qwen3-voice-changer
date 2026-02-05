# coding=utf-8
# Installation instructions for pyaudio:
# APPLE Mac OS X
#   brew install portaudio
#   pip install pyaudio
# Debian/Ubuntu
#   sudo apt-get install python-pyaudio python3-pyaudio
#   or
#   pip install pyaudio
# CentOS
#   sudo yum install -y portaudio portaudio-devel && pip install pyaudio
# Microsoft Windows
#   python -m pip install pyaudio

import pyaudio
import os
import requests
import base64
import pathlib
import threading
import time
import wave
import dashscope  # DashScope Python SDK 版本需要不低于1.23.9
from dashscope.audio.qwen_tts_realtime import QwenTtsRealtime, QwenTtsRealtimeCallback, AudioFormat

# ======= 常量配置 =======
DEFAULT_TARGET_MODEL = "qwen3-tts-vc-realtime-2026-01-15"  # 声音复刻、语音合成要使用相同的模型
DEFAULT_PREFERRED_NAME = "guanyu"
DEFAULT_AUDIO_MIME_TYPE = "audio/mpeg"
VOICE_FILE_PATH = "voice.mp3"  # 用于声音复刻的本地音频文件的相对路径
OUTPUT_FILE_PATH = "output.wav"  # 保存合成音频的路径
VOICE_ID_PATH = "voice_id.txt"   # 保存生成的 voice id

TEXT_TO_SYNTHESIZE = [
    '对吧~我就特别喜欢这种超市，',
    '尤其是过年的时候',
    '去逛超市',
    '就会觉得',
    '超级超级开心！',
    '想买好多好多的东西呢！'
]

def create_voice(file_path: str,
                 target_model: str = DEFAULT_TARGET_MODEL,
                 preferred_name: str = DEFAULT_PREFERRED_NAME,
                 audio_mime_type: str = DEFAULT_AUDIO_MIME_TYPE,
                 force_refresh: bool = False) -> str:
    """
    创建音色，并返回 voice 参数
    """
    # 检查本地是否有缓存的 voice id
    if not force_refresh and os.path.exists(VOICE_ID_PATH):
        try:
            with open(VOICE_ID_PATH, 'r', encoding='utf-8') as f:
                voice_id = f.read().strip()
                if voice_id:
                    print(f"[System] 使用本地缓存的 Voice ID: {voice_id}")
                    return voice_id
        except Exception as e:
            print(f"[Warning] 读取本地 Voice ID 失败: {e}")

    # 新加坡地域和北京地域的API Key不同。获取API Key：https://www.alibabacloud.com/help/zh/model-studio/get-api-key
    # 若没有配置环境变量，请用百炼API Key将下行替换为：api_key = "sk-xxx"
    api_key = os.environ.get('DASHSCOPE_API_KEY', "sk-16737f3d80e74e678afb7b76e9a361af")

    file_path_obj = pathlib.Path(file_path)
    if not file_path_obj.exists():
        raise FileNotFoundError(f"音频文件不存在: {file_path}")

    base64_str = base64.b64encode(file_path_obj.read_bytes()).decode()
    data_uri = f"data:{audio_mime_type};base64,{base64_str}"

    # 以下为新加坡地域url，若使用北京地域的模型，需将url替换为：https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization
    url = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization"
    payload = {
        "model": "qwen-voice-enrollment", # 不要修改该值
        "input": {
            "action": "create",
            "target_model": target_model,
            "preferred_name": preferred_name,
            "audio": {"data": data_uri}
        }
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    resp = requests.post(url, json=payload, headers=headers)
    if resp.status_code != 200:
        raise RuntimeError(f"创建 voice 失败: {resp.status_code}, {resp.text}")

    try:
        voice_id = resp.json()["output"]["voice"]
        # 保存 voice id 到本地
        with open(VOICE_ID_PATH, 'w', encoding='utf-8') as f:
            f.write(voice_id)
        print(f"[System] 新建 Voice ID 已保存: {voice_id}")
        return voice_id
    except (KeyError, ValueError) as e:
        raise RuntimeError(f"解析 voice 响应失败: {e}")

def init_dashscope_api_key():
    """
    初始化 dashscope SDK 的 API key
    """
    # 新加坡地域和北京地域的API Key不同。获取API Key：https://www.alibabacloud.com/help/zh/model-studio/get-api-key
    # 若没有配置环境变量，请用百炼API Key将下行替换为：dashscope.api_key = "sk-xxx"
    dashscope.api_key = os.environ.get('DASHSCOPE_API_KEY', "sk-16737f3d80e74e678afb7b76e9a361af")

# ======= 回调类 =======
class MyCallback(QwenTtsRealtimeCallback):
    """
    自定义 TTS 流式回调
    """
    def __init__(self, output_device_index=None):
        self.complete_event = threading.Event()
        self._player = pyaudio.PyAudio()
        self._stream = self._player.open(
            format=pyaudio.paInt16, 
            channels=1, 
            rate=24000, 
            output=True,
            output_device_index=output_device_index
        )
        self._wav_file = wave.open(OUTPUT_FILE_PATH, 'wb')
        self._wav_file.setnchannels(1)
        self._wav_file.setsampwidth(self._player.get_sample_size(pyaudio.paInt16))
        self._wav_file.setframerate(24000)

    def on_open(self) -> None:
        print('[TTS] 连接已建立')

    def on_close(self, close_status_code, close_msg) -> None:
        self._stream.stop_stream()
        self._stream.close()
        self._player.terminate()
        if self._wav_file:
            self._wav_file.close()
            print(f'[TTS] 音频已保存至: {OUTPUT_FILE_PATH}')
        print(f'[TTS] 连接关闭 code={close_status_code}, msg={close_msg}')

    def on_event(self, response: dict) -> None:
        try:
            event_type = response.get('type', '')
            if event_type == 'session.created':
                print(f'[TTS] 会话开始: {response["session"]["id"]}')
            elif event_type == 'response.audio.delta':
                audio_data = base64.b64decode(response['delta'])
                self._stream.write(audio_data)
                if self._wav_file:
                    self._wav_file.writeframes(audio_data)
            elif event_type == 'response.done':
                print(f'[TTS] 响应完成, Response ID: {qwen_tts_realtime.get_last_response_id()}')
            elif event_type == 'session.finished':
                print('[TTS] 会话结束')
                self.complete_event.set()
        except Exception as e:
            print(f'[Error] 处理回调事件异常: {e}')

    def wait_for_finished(self):
        self.complete_event.wait()

class TTSClient:
    def __init__(self, voice_file_path=VOICE_FILE_PATH, output_device_index=None):
        init_dashscope_api_key()
        self.client = None
        self.callback = None
        self.output_device_index = output_device_index
        # 预先获取 voice_id
        self.voice_id = create_voice(voice_file_path)

    def connect(self):
        if self.client:
            return

        print('[TTS] Connecting...')
        self.callback = MyCallback(output_device_index=self.output_device_index)
        self.client = QwenTtsRealtime(
            model=DEFAULT_TARGET_MODEL,
            callback=self.callback,
            # 以下为新加坡地域url，若使用北京地域的模型，需将url替换为：wss://dashscope.aliyuncs.com/api-ws/v1/realtime
            url='wss://dashscope.aliyuncs.com/api-ws/v1/realtime'
        )
        self.client.connect()
        print('[TTS] Connected.')

    def close(self):
        if self.client:
            # 这里的close逻辑取决于SDK，通常没有显式的close方法在QwenTtsRealtime? 
            # 假设不需要显式close client对象，或者client会自动处理
            # 这里的callback有close资源
            pass
        # 重新创建callback意味着重置pyaudio等
        # 目前MyCallback在__init__里开了pyaudio，在on_close里关了。
        # 如果连接断了，on_close被调用，pyaudio被关了。
        # 下次connect需要新的callback。
        self.client = None
        self.callback = None

    def synthesize(self, text):
        if not self.client:
            self.connect()

        # 重置完成事件
        self.callback.complete_event.clear()

        # sample_rate for tts, range [8000,16000,24000,48000]
        # volume for tts, range [0,100] default is 50
        try:
            self.client.update_session(
                voice=self.voice_id,
                response_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
                volume=100,
                mode='server_commit'
            )

            print(f'[发送文本]: {text}')
            self.client.append_text(text)
            time.sleep(0.1)

            self.client.finish()
            self.callback.wait_for_finished()
            
            print(f'[Metric] session_id={self.client.get_session_id()}, '
                  f'first_audio_delay={self.client.get_first_audio_delay()}s')
            
        except Exception as e:
            print(f"[TTS] Error: {e}")
            self.close()
            raise e

def synthesize_text(text):
    """Legacy function"""
    client = TTSClient()
    try:
        client.synthesize(text)
    except Exception as e:
        print(f"Error in TTS: {e}")
    # 注意：MyCallback的on_close会关闭pyaudio，这里如果client不复用，
    # 实际上每次都会创建新的pyaudio。
    # 如果复用client，MyCallback也会复用，pyaudio保持打开。
    # 但是QwenTtsRealtime的finish之后，连接是否还可用？
    # 假设finish后连接可用（Session结束，Connection保持）。
    # 如果不可用，上面的异常处理会触发close，下次connect。
    
# ======= 主执行逻辑 =======
if __name__ == '__main__':
    client = TTSClient()
    client.connect()
    for text_chunk in TEXT_TO_SYNTHESIZE:
        client.synthesize(text_chunk)