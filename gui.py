import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import pyaudio
import threading
import queue
import sys
import time
import re
from asr import ASRClient
from qwen3tts import TTSClient, create_voice
import os
import dashscope
import json

# Configuration
CHUNK = 3200
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000

class RedirectText(object):
    def __init__(self, text_ctrl):
        self.output = text_ctrl

    def write(self, string):
        self.output.insert(tk.END, string)
        self.output.see(tk.END)

    def flush(self):
        pass

class VoiceChangerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("实时变声器 (Qwen)")
        self.root.geometry("600x500")

        self.p = pyaudio.PyAudio()
        self.is_running = False
        self.thread = None
        self.stop_event = threading.Event()

        # Load Config
        self.config_file = os.path.join(self.get_app_path(), 'config.json')
        self.config = self.load_config()
        
        # Apply API Key from config if exists
        if 'api_key' in self.config and self.config['api_key']:
            os.environ['DASHSCOPE_API_KEY'] = self.config['api_key']
            dashscope.api_key = self.config['api_key']

        # API Key Configuration
        frame_api = ttk.LabelFrame(root, text="API Key 配置")
        frame_api.pack(fill="x", padx=10, pady=5)
        
        ttk.Label(frame_api, text="DashScope API Key:").pack(side="left", padx=5)
        self.api_key_var = tk.StringVar()
        # Try to load existing key from environment or default
        default_key = os.environ.get('DASHSCOPE_API_KEY', '')
        self.api_key_var.set(default_key)
        
        entry_api = ttk.Entry(frame_api, textvariable=self.api_key_var, width=40)
        entry_api.pack(side="left", fill="x", expand=True, padx=5, pady=5)
        
        btn_save_api = ttk.Button(frame_api, text="保存并更新", command=self.save_api_key)
        btn_save_api.pack(side="right", padx=5, pady=5)

        # Voice File Selection
        frame_voice = ttk.LabelFrame(root, text="声音复刻文件")
        frame_voice.pack(fill="x", padx=10, pady=5)
        
        self.voice_path_var = tk.StringVar(value=os.path.abspath("voice.mp3"))
        entry_voice = ttk.Entry(frame_voice, textvariable=self.voice_path_var)
        entry_voice.pack(side="left", fill="x", expand=True, padx=5, pady=5)
        btn_voice = ttk.Button(frame_voice, text="浏览", command=self.browse_voice_file)
        btn_voice.pack(side="right", padx=5, pady=5)

        # Device Selection
        frame_device = ttk.LabelFrame(root, text="音频设备")
        frame_device.pack(fill="x", padx=10, pady=5)

        # Input Device
        ttk.Label(frame_device, text="输入设备 (麦克风):").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.input_device_combo = ttk.Combobox(frame_device, state="readonly", width=50)
        self.input_device_combo.grid(row=0, column=1, padx=5, pady=5)

        # Output Device
        ttk.Label(frame_device, text="输出设备 (扬声器):").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.output_device_combo = ttk.Combobox(frame_device, state="readonly", width=50)
        self.output_device_combo.grid(row=1, column=1, padx=5, pady=5)

        self.refresh_devices()

        # Control Buttons
        frame_ctrl = ttk.Frame(root)
        frame_ctrl.pack(fill="x", padx=10, pady=10)
        
        self.btn_start = ttk.Button(frame_ctrl, text="开始变声", command=self.start_changing)
        self.btn_start.pack(side="left", padx=20, expand=True)
        
        self.btn_stop = ttk.Button(frame_ctrl, text="停止", command=self.stop_changing, state="disabled")
        self.btn_stop.pack(side="right", padx=20, expand=True)

        # Log Area
        frame_log = ttk.LabelFrame(root, text="日志")
        frame_log.pack(fill="both", expand=True, padx=10, pady=5)
        
        self.log_text = scrolledtext.ScrolledText(frame_log, height=10)
        self.log_text.pack(fill="both", expand=True, padx=5, pady=5)

        # Redirect stdout/stderr
        sys.stdout = RedirectText(self.log_text)
        sys.stderr = RedirectText(self.log_text)

    def get_app_path(self):
        if getattr(sys, 'frozen', False):
            # Running as compiled exe
            return os.path.dirname(sys.executable)
        else:
            # Running as script
            return os.path.dirname(os.path.abspath(__file__))

    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"读取配置文件失败: {e}")
        return {}

    def save_config(self):
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
            print(f"配置已保存到: {self.config_file}")
        except Exception as e:
            print(f"保存配置文件失败: {e}")

    def save_api_key(self):
        new_key = self.api_key_var.get().strip()
        if not new_key:
            messagebox.showwarning("警告", "API Key 不能为空！")
            return
            
        print(f"正在更新 API Key 为: {new_key[:6]}******")
        
        # 1. Update current process environment
        os.environ['DASHSCOPE_API_KEY'] = new_key
        dashscope.api_key = new_key
        
        # 2. Update config file
        self.config['api_key'] = new_key
        self.save_config()
            
        messagebox.showinfo("成功", "API Key 已更新并保存到 config.json！\n无需重启程序即可生效。")

    def refresh_devices(self):
        self.input_devices = []
        self.output_devices = []
        
        info = self.p.get_host_api_info_by_index(0)
        numdevices = info.get('deviceCount')
        
        for i in range(0, numdevices):
            dev = self.p.get_device_info_by_host_api_device_index(0, i)
            name = dev.get('name')
            if dev.get('maxInputChannels') > 0:
                self.input_devices.append((name, i))
            if dev.get('maxOutputChannels') > 0:
                self.output_devices.append((name, i))
        
        self.input_device_combo['values'] = [d[0] for d in self.input_devices]
        self.output_device_combo['values'] = [d[0] for d in self.output_devices]
        
        if self.input_devices:
            self.input_device_combo.current(0)
        if self.output_devices:
            self.output_device_combo.current(0)

    def browse_voice_file(self):
        filename = filedialog.askopenfilename(filetypes=[("音频文件", "*.mp3 *.wav *.m4a")])
        if filename:
            self.voice_path_var.set(filename)
            self.generate_voice_id(filename)

    def generate_voice_id(self, filename):
        # Disable start button while generating
        self.btn_start.config(state="disabled")
        
        def task():
            print(f"正在为 {filename} 生成新音色...")
            try:
                # Force refresh because user explicitly changed the file
                create_voice(filename, force_refresh=True)
                print(f"音色生成完毕。")
            except Exception as e:
                print(f"音色生成失败: {e}")
            finally:
                # Re-enable start button
                if not self.is_running:
                     self.root.after(0, lambda: self.btn_start.config(state="normal"))

        threading.Thread(target=task).start()

    def get_selected_input_index(self):
        idx = self.input_device_combo.current()
        if idx >= 0:
            return self.input_devices[idx][1]
        return None

    def get_selected_output_index(self):
        idx = self.output_device_combo.current()
        if idx >= 0:
            return self.output_devices[idx][1]
        return None

    def start_changing(self):
        voice_path = self.voice_path_var.get()
        if not os.path.exists(voice_path):
            print(f"错误：未找到声音文件：{voice_path}")
            return

        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.is_running = True
        self.stop_event.clear()
        
        input_idx = self.get_selected_input_index()
        output_idx = self.get_selected_output_index()
        
        self.thread = threading.Thread(target=self.run_voice_loop, args=(voice_path, input_idx, output_idx))
        self.thread.start()

    def stop_changing(self):
        self.is_running = False
        self.stop_event.set()
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        print("正在停止... 请等待资源释放。")

    def run_voice_loop(self, voice_path, input_idx, output_idx):
        print(f"开始运行，使用声音文件：{voice_path}")
        print(f"输入设备索引：{input_idx}，输出设备索引：{output_idx}")
        
        tts_queue = queue.Queue()
        asr_client = None
        tts_client = None
        stream = None
        
        try:
            # Init Clients
            asr_client = ASRClient()
            asr_client.connect()
            
            def on_text(text):
                if text:
                    tts_queue.put(text)
            
            asr_client.set_callback(on_text)
            
            # Init TTS with custom voice and output device
            tts_client = TTSClient(voice_file_path=voice_path, output_device_index=output_idx)
            tts_client.connect()
            
            # Init Mic Stream
            stream = self.p.open(format=FORMAT,
                                 channels=CHANNELS,
                                 rate=RATE,
                                 input=True,
                                 input_device_index=input_idx,
                                 frames_per_buffer=CHUNK)
            
            asr_client.start_stream()
            print("正在监听...")
            
            while self.is_running and not self.stop_event.is_set():
                # 1. Read Audio
                try:
                    data = stream.read(CHUNK, exception_on_overflow=False)
                except IOError as e:
                    print(f"读取错误：{e}")
                    continue
                
                # 2. Check TTS
                try:
                    text_to_speak = tts_queue.get_nowait()
                    print(f"\n[TTS] 正在播放：{text_to_speak}")
                    
                    stream.stop_stream()
                    try:
                        tts_client.synthesize(text_to_speak)
                    except Exception as e:
                        print(f"TTS 错误：{e}")
                    
                    print("正在监听...")
                    stream.start_stream()
                    tts_queue.task_done()
                    continue
                except queue.Empty:
                    pass
                
                # 3. Send to ASR
                try:
                    asr_client.send_chunk(data)
                except Exception as e:
                    print(f"ASR 发送错误：{e}")
        
        except Exception as e:
            print(f"循环错误：{e}")
        finally:
            print("正在清理资源...")
            if stream:
                stream.stop_stream()
                stream.close()
            if asr_client:
                asr_client.stop_stream()
                asr_client.close()
            if tts_client:
                tts_client.close()
            print("已停止。")

if __name__ == "__main__":
    root = tk.Tk()
    app = VoiceChangerGUI(root)
    root.mainloop()
