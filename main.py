import pyaudio
import os
import time
import queue
from asr import ASRClient
from qwen3tts import TTSClient

# Configuration
CHUNK = 3200  # chunk size for streaming (0.2s for 16k)
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000

def main():
    print("=== Voice Assistant Demo (Streaming) ===")
    print("Initializing clients...")
    
    # Message queue for TTS
    tts_queue = queue.Queue()

    try:
        asr_client = ASRClient()
        asr_client.connect()
        
        # Callback to handle recognized text
        def on_text(text):
            if text:
                tts_queue.put(text)
        
        asr_client.set_callback(on_text)
        
        tts_client = TTSClient()
        tts_client.connect()
    except Exception as e:
        print(f"Initialization failed: {e}")
        return

    print("Initialization complete. Press Ctrl+C to stop.")
    print("Listening...")

    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    input=True,
                    frames_per_buffer=CHUNK)

    # Start ASR Streaming
    asr_client.start_stream()
    
    try:
        while True:
            # 1. Read Audio Chunk
            try:
                # Read without blocking too long if possible, but PyAudio blocks for chunk duration
                data = stream.read(CHUNK, exception_on_overflow=False)
            except IOError as e:
                print(f"Audio read error: {e}")
                continue

            # 2. Check for TTS task
            try:
                # Non-blocking check
                text_to_speak = tts_queue.get_nowait()
                
                print(f"\n[TTS] Speaking: {text_to_speak}")
                
                # Pause recording/sending while speaking (to avoid echo)
                # Ideally stop stream to clear buffer
                stream.stop_stream()
                
                try:
                    tts_client.synthesize(text_to_speak)
                except Exception as e:
                    print(f"TTS Error: {e}")
                
                # Resume recording
                print("Listening...")
                stream.start_stream()
                
                # Clear queue done
                tts_queue.task_done()
                
                # Skip sending the current chunk as it might be old or noise
                continue
                
            except queue.Empty:
                pass

            # 3. Send Chunk to ASR
            try:
                asr_client.send_chunk(data)
            except Exception as e:
                print(f"ASR Send Error: {e}")
                # Try to reconnect?
                pass
                
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        print("Cleaning up...")
        stream.stop_stream()
        stream.close()
        p.terminate()
        
        asr_client.stop_stream()
        asr_client.close()
        tts_client.close()

if __name__ == "__main__":
    main()
