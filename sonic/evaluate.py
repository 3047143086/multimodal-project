import os
import cv2
import torch
import numpy as np
from PIL import Image
from tqdm import tqdm
import json
import argparse
from pathlib import Path


def get_video_frames(video_path):
    """读取视频所有帧"""
    cap = cv2.VideoCapture(video_path)
    frames = []
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    cap.release()
    return frames


def calc_psnr(img1, img2):
    """计算PSNR"""
    from skimage.metrics import peak_signal_noise_ratio
    return peak_signal_noise_ratio(img1, img2)


def calc_ssim(img1, img2):
    """计算SSIM"""
    from skimage.metrics import structural_similarity
    return structural_similarity(img1, img2, channel_axis=-1)


def calc_lpips(img1, img2, model=None):
    """计算LPIPS感知相似度"""
    import lpips
    if model is None:
        model = lpips.LPIPS(net='alex').cuda()

    def to_tensor(img):
        t = torch.FloatTensor(img).permute(2, 0, 1) / 255.0
        return t.unsqueeze(0).cuda() * 2 - 1

    t1, t2 = to_tensor(img1), to_tensor(img2)
    return model(t1, t2).item()


def calc_face_similarity(img1, img2, detector=None):
    """计算人脸相似度（身份保持）"""
    import insightface
    from insightface.app import FaceAnalysis

    if detector is None:
        detector = FaceAnalysis(name='buffalo_l')
        detector.prepare(ctx_id=0, det_size=(640, 640))

    faces1 = detector.get(img1)
    faces2 = detector.get(img2)

    if not faces1 or not faces2:
        return None

    feat1 = faces1[0].normed_embedding.reshape(1, -1)
    feat2 = faces2[0].normed_embedding.reshape(1, -1)
    sim = np.dot(feat1, feat2.T)[0, 0]
    return float(sim)


def calc_lip_sync_error(video_path, audio_path):
    """
    计算唇形同步误差
    LSE-C (Confidence): 越高越好
    LSE-D (Distance): 越低越好
    """
    try:
        from talknet import TalkNet
        model = TalkNet()
        model.loadParameters("checkpoints/TalkNet.model")
        # 简化：这里返回占位符
        # 实际使用需要安装TalkNet或SyncNet
        return {"LSE-C": None, "LSE-D": None, "note": "需要安装SyncNet"}
    except ImportError:
        return {"LSE-C": None, "LSE-D": None, "note": "未安装SyncNet"}


class SonicEvaluator:
    def __init__(self, sonic_pipe):
        self.pipe = sonic_pipe
        self.lpips_model = None
        self.face_detector = None

    def evaluate_single(self, image_path, audio_path, gt_video_path=None):
        """评测单个样本"""
        results = {}

        # 生成视频
        output_path = image_path.replace('.png', '_output.mp4').replace('.jpg', '_output.mp4')
        video_path = self.pipe.process(
            image_path, audio_path, output_path,
            min_resolution=512, inference_steps=25, dynamic_scale=1.0
        )

        if video_path == -1:
            return {"error": "生成失败，未检测到人脸"}

        # 读取生成视频帧
        gen_frames = get_video_frames(video_path)
        if not gen_frames:
            return {"error": "视频读取失败"}

        results["num_frames"] = len(gen_frames)
        results["video_path"] = video_path

        # 计算第一帧与原图的相似度
        source_img = cv2.cvtColor(cv2.imread(image_path), cv2.COLOR_BGR2RGB)
        # resize到同尺寸
        h, w = gen_frames[0].shape[:2]
        source_img_resized = cv2.resize(source_img, (w, h))

        results["first_frame_psnr"] = calc_psnr(gen_frames[0], source_img_resized)
        results["first_frame_ssim"] = calc_ssim(gen_frames[0], source_img_resized)

        # 计算LPIPS
        if torch.cuda.is_available():
            if self.lpips_model is None:
                self.lpips_model = lpips.LPIPS(net='alex').cuda()
            results["first_frame_lpips"] = calc_lpips(
                gen_frames[0], source_img_resized, self.lpips_model
            )

        # 计算身份保持度
        try:
            face_sim = calc_face_similarity(source_img, gen_frames[0], self.face_detector)
            if face_sim is not None:
                results["identity_similarity_first"] = face_sim
        except Exception as e:
            results["identity_similarity_first"] = f"计算失败: {e}"

        # 计算时序一致性（相邻帧相似度）
        temporal_scores = []
        for i in range(min(len(gen_frames) - 1, 30)):
            ssim = calc_ssim(gen_frames[i], gen_frames[i + 1])
            temporal_scores.append(ssim)
        results["temporal_consistency_mean"] = np.mean(temporal_scores) if temporal_scores else None
        results["temporal_consistency_std"] = np.std(temporal_scores) if temporal_scores else None

        # 身份保持度 - 所有关键帧
        identity_scores = []
        sample_interval = max(1, len(gen_frames) // 5)
        for i in range(0, len(gen_frames), sample_interval):
            try:
                sim = calc_face_similarity(source_img, gen_frames[i], self.face_detector)
                if sim is not None:
                    identity_scores.append(sim)
            except Exception:
                pass
        if identity_scores:
            results["identity_similarity_mean"] = float(np.mean(identity_scores))
            results["identity_similarity_min"] = float(np.min(identity_scores))

        # 如果有GT视频，计算与GT的指标
        if gt_video_path and os.path.exists(gt_video_path):
            gt_frames = get_video_frames(gt_video_path)
            min_len = min(len(gt_frames), len(gen_frames))

            psnr_list, ssim_list = [], []
            for i in range(min_len):
                gt_resized = cv2.resize(gt_frames[i], (w, h))
                psnr_list.append(calc_psnr(gen_frames[i], gt_resized))
                ssim_list.append(calc_ssim(gen_frames[i], gt_resized))

            results["vs_gt_psnr_mean"] = float(np.mean(psnr_list))
            results["vs_gt_ssim_mean"] = float(np.mean(ssim_list))

        return results

    def evaluate_batch(self, test_pairs, output_file="evaluation_results.json"):
        """批量评测"""
        all_results = []
        for pair in tqdm(test_pairs, desc="评测进度"):
            result = self.evaluate_single(
                pair["image"], pair["audio"], pair.get("gt_video")
            )
            result["image"] = pair["image"]
            result["audio"] = pair["audio"]
            all_results.append(result)

        # 汇总统计
        summary = {}
        metric_keys = ["first_frame_psnr", "first_frame_ssim", "first_frame_lpips",
                        "identity_similarity_mean", "temporal_consistency_mean"]

        for key in metric_keys:
            values = [r[key] for r in all_results if isinstance(r.get(key), (int, float))]
            if values:
                summary[f"{key}_mean"] = float(np.mean(values))
                summary[f"{key}_std"] = float(np.std(values))

        output = {"summary": summary, "details": all_results}

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        print("\n===== 评测结果汇总 =====")
        for key, val in summary.items():
            print(f"  {key}: {val:.4f}" if isinstance(val, float) else f"  {key}: {val}")

        return output


def evaluate_performance(sonic_pipe, image_path, audio_path, runs=3):
    """性能评测"""
    import time

    results = {}

    # 预处理耗时
    t0 = time.time()
    face_info = sonic_pipe.preprocess(image_path, expand_ratio=0.5)
    t1 = time.time()
    results["preprocess_time"] = t1 - t0

    # 推理耗时（多次取平均）
    times = []
    for i in range(runs):
        output_path = f'./outputs/perf_test_{i}.mp4'
        t0 = time.time()
        sonic_pipe.process(
            image_path, audio_path, output_path,
            min_resolution=512, inference_steps=25, dynamic_scale=1.0
        )
        t1 = time.time()
        times.append(t1 - t0)
        if os.path.exists(output_path):
            os.remove(output_path)

    results["inference_time_mean"] = float(np.mean(times))
    results["inference_time_std"] = float(np.std(times))

    # 显存占用
    if torch.cuda.is_available():
        results["gpu_memory_allocated_gb"] = torch.cuda.max_memory_allocated() / 1024**3

    return results


def evaluate_robustness(sonic_pipe, test_cases):
    """鲁棒性评测"""
    results = []

    for case in test_cases:
        image_path = case["image"]
        audio_path = case["audio"]
        category = case.get("category", "default")

        try:
            face_info = sonic_pipe.preprocess(image_path, expand_ratio=0.5)
            if face_info['face_num'] == 1:
                output_path = f'./outputs/robust_{category}.mp4'
                video_path = sonic_pipe.process(
                    image_path, audio_path, output_path,
                    min_resolution=512, inference_steps=25, dynamic_scale=1.0
                )
                status = "success" if video_path != -1 else "fail"
            else:
                status = f"face_num={face_info['face_num']}"
        except Exception as e:
            status = f"error: {str(e)[:50]}"

        results.append({
            "category": category,
            "image": image_path,
            "status": status
        })

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sonic系统评测")
    parser.add_argument('--mode', type=str, default='quality',
                        choices=['quality', 'performance', 'robustness', 'all'],
                        help='评测模式')
    parser.add_argument('--image', type=str, help='输入图像路径')
    parser.add_argument('--audio', type=str, help='输入音频路径')
    parser.add_argument('--gt', type=str, default=None, help='GT视频路径（可选）')
    parser.add_argument('--runs', type=int, default=3, help='性能评测重复次数')
    args = parser.parse_args()

    from sonic import Sonic
    pipe = Sonic(0)

    if args.mode in ['quality', 'all']:
        evaluator = SonicEvaluator(pipe)
        if args.image and args.audio:
            result = evaluator.evaluate_single(args.image, args.audio, args.gt)
            print("\n===== 单样本评测结果 =====")
            for k, v in result.items():
                print(f"  {k}: {v}")

    if args.mode in ['performance', 'all']:
        if args.image and args.audio:
            result = evaluate_performance(pipe, args.image, args.audio, args.runs)
            print("\n===== 性能评测结果 =====")
            for k, v in result.items():
                print(f"  {k}: {v}")

    if args.mode in ['robustness', 'all']:
        test_cases = [
            {"image": "examples/image/anime1.png", "audio": "examples/wav/talk_female_english_10s.MP3", "category": "anime"},
            {"image": "examples/image/hair.png", "audio": "examples/wav/sing_female_10s.wav", "category": "real_person"},
            {"image": "examples/image/leonnado.jpg", "audio": "examples/wav/talk_male_law_10s.wav", "category": "male"},
        ]
        result = evaluate_robustness(pipe, test_cases)
        print("\n===== 鲁棒性评测结果 =====")
        for r in result:
            print(f"  [{r['category']}] {r['status']}")
