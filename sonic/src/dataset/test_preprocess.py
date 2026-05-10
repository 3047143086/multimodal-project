import os
import numpy as np
from PIL import Image
import torch
import torchvision.transforms as transforms
from transformers import CLIPImageProcessor, WhisperFeatureExtractor
import librosa


def process_bbox(bbox, expand_radio, height, width):
    """
    raw_vid_path:
    bbox: format: x1, y1, x2, y2
    radio: expand radio against bbox size
    height,width: source image height and width
    """

    def expand(bbox, ratio, height, width):
        bbox_h = bbox[3] - bbox[1]
        bbox_w = bbox[2] - bbox[0]
        expand_x1 = max(bbox[0] - ratio * bbox_w, 0)
        expand_y1 = max(bbox[1] - ratio * bbox_h, 0)
        expand_x2 = min(bbox[2] + ratio * bbox_w, width)
        expand_y2 = min(bbox[3] + ratio * bbox_h, height)
        return [expand_x1, expand_y1, expand_x2, expand_y2]

    def to_square(bbox_src, bbox_expend, height, width):
        h = bbox_expend[3] - bbox_expend[1]
        w = bbox_expend[2] - bbox_expend[0]
        c_h = (bbox_expend[1] + bbox_expend[3]) / 2
        c_w = (bbox_expend[0] + bbox_expend[2]) / 2
        c = min(h, w) / 2
        c_src_h = (bbox_src[1] + bbox_src[3]) / 2
        c_src_w = (bbox_src[0] + bbox_src[2]) / 2
        s_h, s_w = 0, 0
        if w < h:
            d = abs((h - w) / 2)
            s_h = min(d, abs(c_src_h - c_h))
            s_h = s_h if c_src_h > c_h else -s_h
        else:
            d = abs((h - w) / 2)
            s_w = min(d, abs(c_src_w - c_w))
            s_w = s_w if c_src_w > c_w else -s_w
        c_h = c_h + s_h
        c_w = c_w + s_w
        square_x1 = c_w - c
        square_y1 = c_h - c
        square_x2 = c_w + c
        square_y2 = c_h + c
        ww = square_x2 - square_x1
        hh = square_y2 - square_y1
        cc_x = (square_x1 + square_x2) / 2
        cc_y = (square_y1 + square_y2) / 2
        ww = hh = min(ww, hh)
        x1 = round(cc_x - ww / 2)
        x2 = round(cc_x + ww / 2)
        y1 = round(cc_y - hh / 2)
        y2 = round(cc_y + hh / 2)
        return [x1, y1, x2, y2]

    bbox_expend = expand(bbox, expand_radio, height=height, width=width)
    processed_bbox = to_square(bbox, bbox_expend, height=height, width=width)
    return processed_bbox


def get_audio_feature(audio_path, audio_processor):
    # Load audio waveform
    audio_input, sampling_rate = librosa.load(audio_path, sr=16000)
    assert sampling_rate == 16000

    audio_features = []
    window = 750 * 640
    for i in range(0, len(audio_input), window):
        chunk = audio_input[i : i + window]
        audio_feature = audio_processor(
            chunk,
            sampling_rate=sampling_rate,
            return_tensors="pt",
        ).input_features
        audio_features.append(audio_feature)
    audio_features = torch.cat(audio_features, dim=-1)
    return audio_features, len(audio_input) // 640


def image_audio_to_tensor(
    align_instance,
    image_processor,
    audio_processor,
    image_path,
    audio_path,
    limit=100,
    image_size=512,
    area=1.25,
):
    # Prepare transforms
    to_tensor = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
    ])
    mask_to_tensor = transforms.Compose([transforms.ToTensor()])

    # Load and align face
    im = Image.open(image_path).convert("RGB")
    w, h = im.size
    _, _, bboxes = align_instance(np.array(im)[:, :, [2, 1, 0]], maxface=True)
    if not bboxes:
        return None
    x1, y1, ww, hh = bboxes[0]
    x2, y2 = x1 + ww, y1 + hh

    # Create mask image
    mask = np.zeros_like(np.array(im))
    ww_a, hh_a = (x2 - x1) * area, (y2 - y1) * area
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    x1_m = max(cx - ww_a // 2, 0)
    y1_m = max(cy - hh_a // 2, 0)
    x2_m = min(cx + ww_a // 2, w)
    y2_m = min(cy + hh_a // 2, h)
    mask[int(y1_m) : int(y2_m), int(x1_m) : int(x2_m)] = 255
    mask_img = Image.fromarray(mask)

    # Resize if needed
    scale = image_size / min(w, h)
    new_w = round(w * scale / 64) * 64
    new_h = round(h * scale / 64) * 64
    if new_w != w or new_h != h:
        im_resized = im.resize((new_w, new_h), Image.LANCZOS)
        mask_img = mask_img.resize((new_w, new_h), Image.LANCZOS)
    else:
        im_resized = im

    # Process image
    clip_image = image_processor(images=im_resized.resize((224, 224), Image.LANCZOS), return_tensors="pt").pixel_values[0]

    # Debug prints for audio processing
    print(f"[DEBUG] Calling get_audio_feature with audio_path = {audio_path}")
    print(f"[DEBUG:get_audio_feature] received processor = {type(audio_processor)}")

    # Extract audio features
    audio_feat, audio_len = get_audio_feature(audio_path, audio_processor)

    print(f"[DEBUG] get_audio_feature returned: audio_feat shape = {getattr(audio_feat, 'shape', 'N/A')}, audio_len = {audio_len}")

    audio_len = min(limit, audio_len)

    # Build sample dict
    sample = {
        'face_mask': mask_to_tensor(mask_img),
        'ref_img': to_tensor(im_resized),
        'clip_images': clip_image,
        'audio_feature': audio_feat[0],
        'audio_len': audio_len,
    }
    return sample
