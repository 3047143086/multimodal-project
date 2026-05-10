import os
import argparse
from sonic import Sonic

pipe = Sonic(0)


parser = argparse.ArgumentParser()
parser.add_argument('image_path')
parser.add_argument('audio_path')
parser.add_argument('output_path')
parser.add_argument('--dynamic_scale', type=float, default=1.0)
parser.add_argument('--seed', type=int, default=None)

args = parser.parse_args()


face_info = pipe.preprocess(args.image_path, expand_ratio=0.5)
print(face_info)
if face_info['face_num'] >= 0:
    os.makedirs(os.path.dirname(args.output_path), exist_ok=True)
    output_path = pipe.process(args.image_path, args.audio_path, args.output_path, min_resolution=512, inference_steps=25, dynamic_scale=1.0)
