import librosa
import json
import argparse
import os

def audio_analyzer(audio_path, output_dir):
    # 加载音频
    y, sr = librosa.load(audio_path, sr=None)
    duration_sec = librosa.get_duration(y=y, sr=sr)
    sample_rate = sr

    # 推导json文件名
    base_name = os.path.basename(audio_path)
    name = os.path.splitext(base_name)[0]
    output_path = os.path.join(output_dir, f"{name}_data.json")

    # TODO: 特征提取的具体实现（待施工）
    bpm_list = []
    entity_stream = []
    macro_stream = []

    # 组装字典
    contract_data = {
        "meta_data": {
            "title": "",
            "duration_sec": duration_sec,
            "sample_rate": sample_rate,
            "bpm_list": bpm_list
        },
        "entity_stream": entity_stream,
        "macro_stream": macro_stream
    }

    # 写入json文件
    os.makedirs(output_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(contract_data, f, ensure_ascii=False, indent=4)


if __name__ == "__main__":
    '''解析参数'''
    parser = argparse.ArgumentParser(description="analyzer's 参数解析器")
    parser.add_argument("--audio_name", default="Aorist.mp3", help="音频名称")
    args = parser.parse_args()

    '''处理路径问题'''
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # 项目根目录
    audio_path = os.path.join(BASE_DIR, "assets", "audio", f"{args.audio_name}")
    output_dir = os.path.join(BASE_DIR, "assets", "data")

    '''调用音频处理函数'''
    audio_analyzer(audio_path, output_dir)

