import os
import torch
import torch.utils.checkpoint
from PIL import Image
import numpy as np
from omegaconf import OmegaConf
from tqdm import tqdm
import cv2

from diffusers import AutoencoderKLTemporalDecoder
from diffusers.schedulers import EulerDiscreteScheduler
from transformers import WhisperModel, CLIPVisionModelWithProjection
from transformers import WhisperFeatureExtractor, CLIPImageProcessor
from src.utils.util import save_videos_grid, seed_everything
from src.dataset.test_preprocess import process_bbox, image_audio_to_tensor
from src.models.base.unet_spatio_temporal_condition import UNetSpatioTemporalConditionModel, add_ip_adapters
from src.pipelines.pipeline_sonic import SonicPipeline
from src.models.audio_adapter.audio_proj import AudioProjModel
from src.models.audio_adapter.audio_to_bucket import Audio2bucketModel
from src.utils.RIFE.RIFE_HDv3 import RIFEModel
from src.dataset.face_align.align import AlignImage

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def test(
    pipe,
    config,
    wav_enc,
    audio_pe,
    audio2bucket,
    image_encoder,
    width,
    height,
    batch
):
    for k, v in batch.items():
        if isinstance(v, torch.Tensor):
            batch[k] = v.unsqueeze(0).to(pipe.device).float()
    ref_img = batch['ref_img']
    clip_img = batch['clip_images']
    face_mask = batch['face_mask']
    image_embeds = image_encoder(clip_img).image_embeds

    audio_feature = batch['audio_feature']
    audio_len = batch['audio_len']
    step = int(config.step)

    window = 3000
    audio_prompts = []
    last_audio_prompts = []
    for i in range(0, audio_feature.shape[-1], window):
        audio_prompt = wav_enc.encoder(audio_feature[:, :, i:i+window], output_hidden_states=True).hidden_states
        last_audio_prompt = wav_enc.encoder(audio_feature[:, :, i:i+window]).last_hidden_state
        last_audio_prompt = last_audio_prompt.unsqueeze(-2)
        audio_prompt = torch.stack(audio_prompt, dim=2)
        audio_prompts.append(audio_prompt)
        last_audio_prompts.append(last_audio_prompt)

    audio_prompts = torch.cat(audio_prompts, dim=1)
    audio_prompts = audio_prompts[:, :audio_len*2]
    audio_prompts = torch.cat([
        torch.zeros_like(audio_prompts[:, :4]),
        audio_prompts,
        torch.zeros_like(audio_prompts[:, :6])
    ], dim=1)

    last_audio_prompts = torch.cat(last_audio_prompts, dim=1)
    last_audio_prompts = last_audio_prompts[:, :audio_len*2]
    last_audio_prompts = torch.cat([
        torch.zeros_like(last_audio_prompts[:, :24]),
        last_audio_prompts,
        torch.zeros_like(last_audio_prompts[:, :26])
    ], dim=1)

    ref_tensors = []
    cond_audio_tensors = []
    uncond_audio_tensors = []
    motion_buckets = []

    for i in tqdm(range(audio_len // step)):
        audio_clip = audio_prompts[:, i*2*step : i*2*step+10].unsqueeze(0)
        audio_clip_for_bucket = last_audio_prompts[:, i*2*step : i*2*step+50].unsqueeze(0)
        bucket = audio2bucket(audio_clip_for_bucket, image_embeds)
        bucket = bucket * 16 + 16
        motion_buckets.append(bucket[0])

        cond = audio_pe(audio_clip).squeeze(0)
        uncond = audio_pe(torch.zeros_like(audio_clip)).squeeze(0)

        ref_tensors.append(ref_img[0])
        cond_audio_tensors.append(cond[0])
        uncond_audio_tensors.append(uncond[0])

    video = pipe(
        ref_img,
        clip_img,
        face_mask,
        cond_audio_tensors,
        uncond_audio_tensors,
        motion_buckets,
        height=height,
        width=width,
        num_frames=len(cond_audio_tensors),
        decode_chunk_size=config.decode_chunk_size,
        motion_bucket_scale=config.motion_bucket_scale,
        fps=config.fps,
        noise_aug_strength=config.noise_aug_strength,
        min_guidance_scale1=config.min_appearance_guidance_scale,
        max_guidance_scale1=config.max_appearance_guidance_scale,
        min_guidance_scale2=config.audio_guidance_scale,
        max_guidance_scale2=config.audio_guidance_scale,
        overlap=config.overlap,
        shift_offset=config.shift_offset,
        frames_per_batch=config.n_sample_frames,
        num_inference_steps=config.num_inference_steps,
        i2i_noise_strength=config.i2i_noise_strength
    ).frames

    video = (video * 0.5 + 0.5).clamp(0, 1)
    video = video.to(pipe.device).cpu()
    return video


class Sonic:
    config_file = os.path.join(BASE_DIR, 'config/inference/sonic.yaml')
    config = OmegaConf.load(config_file)

    def __init__(self, device_id=0, enable_interpolate_frame=True):
        config = self.config
        config.use_interframe = enable_interpolate_frame

        device = f'cuda:{device_id}' if device_id >= 0 else 'cpu'
        config.pretrained_model_name_or_path = os.path.join(BASE_DIR, config.pretrained_model_name_or_path)

        # Load models
        vae = AutoencoderKLTemporalDecoder.from_pretrained(
            config.pretrained_model_name_or_path, subfolder="vae", variant="fp16"
        )
        scheduler = EulerDiscreteScheduler.from_pretrained(
            config.pretrained_model_name_or_path, subfolder="scheduler"
        )
        vision = CLIPVisionModelWithProjection.from_pretrained(
            config.pretrained_model_name_or_path, subfolder="image_encoder", variant="fp16"
        )
        unet = UNetSpatioTemporalConditionModel.from_pretrained(
            config.pretrained_model_name_or_path, subfolder="unet", variant="fp16"
        )
        add_ip_adapters(unet, [32], [config.ip_audio_scale])

        # Audio adapter models
        audio2token = AudioProjModel(
            seq_len=10, blocks=5, channels=384, intermediate_dim=1024, output_dim=1024, context_tokens=32
        ).to(device)
        audio2bucket = Audio2bucketModel(
            seq_len=50, blocks=1, channels=384, clip_channels=1024,
            intermediate_dim=1024, output_dim=1, context_tokens=2
        ).to(device)

        # Load checkpoints
        unet.load_state_dict(torch.load(os.path.join(BASE_DIR, config.unet_checkpoint_path), map_location="cpu"))
        audio2token.load_state_dict(torch.load(os.path.join(BASE_DIR, config.audio2token_checkpoint_path), map_location="cpu"))
        audio2bucket.load_state_dict(torch.load(os.path.join(BASE_DIR, config.audio2bucket_checkpoint_path), map_location="cpu"))

        # Set dtype
        dtype_map = {"fp16": torch.float16, "fp32": torch.float32, "bf16": torch.bfloat16}
        weight_dtype = dtype_map.get(config.weight_dtype)
        if weight_dtype is None:
            raise ValueError(f"Unsupported weight dtype: {config.weight_dtype}")

        # Whisper model
        whisper = WhisperModel.from_pretrained(
            os.path.join(BASE_DIR, 'checkpoints/whisper-tiny/')
        ).to(device).eval()
        whisper.requires_grad_(False)

        # Processors
        self.image_processor = CLIPImageProcessor.from_pretrained(
            os.path.join(BASE_DIR, 'checkpoints/stable-video-diffusion-img2vid-xt/feature_extractor')
        )
        self.audio_processor = WhisperFeatureExtractor.from_pretrained(
            os.path.join(BASE_DIR, 'checkpoints/whisper-tiny/')
        )

        # Face detector & RIFE
        self.face_det = AlignImage(device, det_path=os.path.join(BASE_DIR, 'checkpoints/yoloface_v5m.pt'))
        if config.use_interframe:
            rife = RIFEModel(device=device)
            rife.load_model(os.path.join(BASE_DIR, 'checkpoints/RIFE/'))
            self.rife = rife

        # Move models
        vision.to(weight_dtype)
        vae.to(weight_dtype)
        unet.to(weight_dtype)

        # Pipeline
        pipe = SonicPipeline(unet=unet, image_encoder=vision, vae=vae, scheduler=scheduler)
        self.pipe = pipe.to(device=device, dtype=weight_dtype)

        # Save refs
        self.whisper = whisper
        self.audio2token = audio2token
        self.audio2bucket = audio2bucket
        self.image_encoder = vision
        self.device = device

        print('init done')

    def preprocess(self, image_path, expand_ratio=1.0):
        img = cv2.imread(image_path)
        h, w = img.shape[:2]
        _, _, bboxes = self.face_det(img, maxface=False)  # 返回所有人脸
        
        processed_bboxes = []
        for box in bboxes:
            x1, y1, ww, hh = box
            processed = process_bbox((x1, y1, x1+ww, y1+hh), 
                                    expand_radio=expand_ratio, 
                                    height=h, width=w)
            processed_bboxes.append(processed)
            
        return {
            'face_num': len(bboxes),
            'crop_bboxes': processed_bboxes  # 返回所有处理后的边界框
        }

    @torch.no_grad()
    def process(
        self, image_path, audio_path, output_path,
        min_resolution=512, inference_steps=25,
        dynamic_scale=1.0, keep_resolution=False, seed=None
    ):
        config = self.config
        if seed:
            config.seed = seed
        config.num_inference_steps = inference_steps
        config.motion_bucket_scale = dynamic_scale
        seed_everything(config.seed)

        # Prepare data
        print(f"[DEBUG] Feature extractor types: image={type(self.image_processor)}, audio={type(self.audio_processor)}")
        test_data = image_audio_to_tensor(
            self.face_det,
            self.image_processor,
            self.audio_processor,
            image_path,
            audio_path,
            limit=config.frame_num,
            image_size=min_resolution,
            area=config.area
        )
        if test_data is None:
            return -1

        raw_img = Image.open(image_path)
        raw_w, raw_h = raw_img.size
        h, w = test_data['ref_img'].shape[-2:]
        resolution = f"{w}x{h}" if not keep_resolution else f"{raw_w//2*2}x{raw_h//2*2}"

        video = test(
            self.pipe, config, wav_enc=self.whisper,
            audio_pe=self.audio2token, audio2bucket=self.audio2bucket,
            image_encoder=self.image_encoder,
            width=w, height=h, batch=test_data
        )

        # Interpolation
        if config.use_interframe:
            out = video.to(self.device)
            seq = []
            L = out.shape[2]
            for i in range(L-1):
                seq.append(out[:, :, i])
                seq.append(self.rife.inference(out[:, :, i], out[:, :, i+1]).clamp(0,1).detach())
            seq.append(out[:, :, -1])
            video = torch.stack(seq, dim=2).cpu()

        tmp_path = output_path.replace('.mp4', '_noaudio.mp4')
        save_videos_grid(video, tmp_path, n_rows=video.shape[0], fps=config.fps * (2 if config.use_interframe else 1))
        ff = (f'ffmpeg -i "{tmp_path}" -i "{audio_path}" -s {resolution} '
              f'-vcodec libx264 -acodec aac -crf 18 -shortest -y "{output_path}"')
        os.system(ff)
        os.remove(tmp_path)

        return output_path