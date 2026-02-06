import logging
import os
import base64
import signal
import sys
import time
import dashscope
from dashscope.audio.qwen_omni import *
from dashscope.audio.qwen_omni.omni_realtime import TranscriptionParams


def setup_logging():
    """配置日志输出"""
    logger = logging.getLogger('dashscope')
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def init_api_key():
    """初始化 API Key"""
    # 新加坡和北京地域的API Key不同。获取API Key：https://help.aliyun.com/zh/model-studio/get-api-key
    # 若没有配置环境变量，请用百炼API Key将下行替换为：dashscope.api_key = "sk-xxx"
    dashscope.api_key = os.environ.get('DASHSCOPE_API_KEY')
    if not dashscope.api_key:
        print('[Warning] DASHSCOPE_API_KEY is not set. Please set it in environment variables or config.')


class MyCallback(OmniRealtimeCallback):
    """实时识别回调处理"""
    def __init__(self, conversation):
        self.conversation = conversation
        self.results = []
        self.on_text_callback = None
        self.handlers = {
            'session.created': self._handle_session_created,
            'conversation.item.input_audio_transcription.completed': self._handle_final_text,
            'conversation.item.input_audio_transcription.text': self._handle_stash_text,
            'input_audio_buffer.speech_started': lambda r: print('======Speech Start======'),
            'input_audio_buffer.speech_stopped': lambda r: print('======Speech Stop======')
        }

    def on_open(self):
        print('Connection opened')

    def on_close(self, code, msg):
        print(f'Connection closed, code: {code}, msg: {msg}')

    def on_event(self, response):
        try:
            handler = self.handlers.get(response['type'])
            if handler:
                handler(response)
        except Exception as e:
            print(f'[Error] {e}')

    def _handle_session_created(self, response):
        print(f"Start session: {response['session']['id']}")

    def _handle_final_text(self, response):
        text = response['transcript']
        print(f"Final recognized text: {text}")
        self.results.append(text)
        if self.on_text_callback:
            self.on_text_callback(text)

    def _handle_stash_text(self, response):
        print(f"Got stash result: {response['stash']}")


def read_audio_chunks(file_path, chunk_size=3200):
    """按块读取音频文件"""
    with open(file_path, 'rb') as f:
        while chunk := f.read(chunk_size):
            yield chunk


def send_audio(conversation, file_path, delay=0.1):
    """发送音频数据"""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Audio file {file_path} does not exist.")

    print("Processing audio file... Press 'Ctrl+C' to stop.")
    for chunk in read_audio_chunks(file_path):
        audio_b64 = base64.b64encode(chunk).decode('ascii')
        conversation.append_audio(audio_b64)
        time.sleep(delay)

def recognize_audio(audio_file_path):
    """Legacy function for backward compatibility"""
    client = ASRClient()
    try:
        return client.recognize(audio_file_path)
    finally:
        client.close()

class ASRClient:
    def __init__(self):
        setup_logging()
        init_api_key()
        self.conversation = None
        self.callback = None
        self.is_streaming = False

    def connect(self):
        """建立连接。如果已连接则忽略。"""
        if self.conversation:
            return

        print("[ASR] Connecting...")
        self.callback = MyCallback(conversation=None)
        self.conversation = OmniRealtimeConversation(
            model='qwen3-asr-flash-realtime',
            url='wss://dashscope.aliyuncs.com/api-ws/v1/realtime',
            callback=self.callback
        )
        self.conversation.callback.conversation = self.conversation
        self.conversation.connect()
        print("[ASR] Connected.")

    def close(self):
        if self.conversation:
            try:
                self.conversation.close()
            except Exception as e:
                print(f"[ASR] Error closing: {e}")
            finally:
                self.conversation = None
                print("[ASR] Connection closed.")
    
    def set_callback(self, callback_func):
        if self.callback:
            self.callback.on_text_callback = callback_func

    def start_stream(self):
        """Start a streaming session"""
        if not self.conversation:
            self.connect()
        
        # If already streaming, maybe we don't need to update session again?
        # But to be safe, update it.
        
        transcription_params = TranscriptionParams(
            language='zh',
            sample_rate=16000,
            input_audio_format="pcm"
        )
        
        self.conversation.update_session(
            output_modalities=[MultiModality.TEXT],
            enable_input_audio_transcription=True,
            transcription_params=transcription_params
        )
        self.is_streaming = True
        print("[ASR] Streaming session started.")

    def send_chunk(self, chunk):
        if not self.conversation:
            return
        audio_b64 = base64.b64encode(chunk).decode('ascii')
        self.conversation.append_audio(audio_b64)

    def stop_stream(self):
        if self.conversation and self.is_streaming:
            self.conversation.end_session()
            self.is_streaming = False
            print("[ASR] Streaming session ended.")

    def recognize(self, audio_file_path):
        """执行一次语音识别"""
        if not self.conversation:
            self.connect()

        # 重置结果
        self.callback.results = []
        
        transcription_params = TranscriptionParams(
            language='zh',
            sample_rate=16000,
            input_audio_format="pcm"
        )

        try:
            self.conversation.update_session(
                output_modalities=[MultiModality.TEXT],
                enable_input_audio_transcription=True,
                transcription_params=transcription_params
            )

            send_audio(self.conversation, audio_file_path)
            self.conversation.end_session()
            
            # 等待结果，这里简单sleep，理想情况应该用Event等待finish
            time.sleep(1) 
        except Exception as e:
            print(f"[ASR] Error occurred: {e}")
            # 如果出错，可能连接已断开，尝试重置
            self.close()
            raise e
        
        return "".join(self.callback.results)

def main():
    setup_logging()
    init_api_key()

    audio_file_path = "./your_audio_file.pcm"
    conversation = OmniRealtimeConversation(
        model='qwen3-asr-flash-realtime',
        # 以下为北京地域url，若使用新加坡地域的模型，需将url替换为：wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime
        url='wss://dashscope.aliyuncs.com/api-ws/v1/realtime',
        callback=MyCallback(conversation=None)  # 暂时传None，稍后注入
    )

    # 注入自身到回调
    conversation.callback.conversation = conversation

    def handle_exit(sig, frame):
        print('Ctrl+C pressed, exiting...')
        conversation.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)

    conversation.connect()

    transcription_params = TranscriptionParams(
        language='zh',
        sample_rate=16000,
        input_audio_format="pcm"
    )

    conversation.update_session(
        output_modalities=[MultiModality.TEXT],
        enable_input_audio_transcription=True,
        transcription_params=transcription_params
    )

    try:
        send_audio(conversation, audio_file_path)
        # send session.finish and wait for finished and close
        conversation.end_session()
    except Exception as e:
        print(f"Error occurred: {e}")
    finally:
        conversation.close()
        print("Audio processing completed.")


if __name__ == '__main__':
    main()