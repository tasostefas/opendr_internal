# Copyright 2020-2023 OpenDR European Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from typing import Callable
import argparse
import time
from logging import getLogger

import numpy as np
import sounddevice as sd

from opendr.perception.speech_transcription import (
    WhisperLearner,
    VoskLearner,
)

logger = getLogger(__name__)


def str2bool(v):
    if isinstance(v, bool):
        return v
    if v.lower() in ("True", "true"):
        return True
    elif v.lower() in ("False", "false"):
        return False
    else:
        raise argparse.ArgumentTypeError("Boolean value expected.")


def record_audio(duration: int, sample_rate: int) -> np.ndarray:
    audio_data = sd.rec(
        int(duration * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
    )
    sd.wait()  # Wait for the recording to finish
    audio_data = np.squeeze(audio_data, axis=-1)

    return audio_data


def transcribe_audio(audio_data: np.ndarray, transcribe_function: Callable):
    output = transcribe_function(audio_data)
    output = output.text

    logger.info("Transcription: ", output)

    return output


def wait_for_start_command(learner, sample_rate):
    while True:
        audio_data = record_audio(1, sample_rate)
        transcription = learner.infer(audio_data).text.lower()
        logger.info(f"User said: {transcription}")

        if "start" in transcription:
            logger.info("Start command received. Starting transcribe.")
            break


def main(
    backbone, duration, interval, model_path, model_name, language, download_dir, device
):
    if backbone == "whisper":
        learner = WhisperLearner(language=language, device=device)
        learner.load(name=model_name, model_path=model_path, download_dir=download_dir)
    elif args.backbone == "vosk":
        learner = VoskLearner()
        learner.load(
            name=model_name,
            model_path=model_path,
            language=language,
            download_dir=download_dir,
        )
    else:
        raise ValueError("invalid backbone")

    # Wait for the user to say "hi whisper" before starting the loop
    sample_rate = 16000
    wait_for_start_command(learner, sample_rate)

    while True:
        # Record the audio
        audio_data = record_audio(duration, sample_rate)

        # Transcribe the recorded audio and check for the "bye whisper" command
        transcription = transcribe_audio(audio_data, learner.infer).lower()

        if "stop" in transcription:
            logger.info("Stop command received. Exiting the program.")
            break

        # Wait for `interval` seconds before starting the next recording
        time.sleep(interval)

    logger.info("Finished transcribe.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Record and transcribe audio every X seconds using the WhisperLearner model."
    )
    parser.add_argument(
        "-d",
        "--duration",
        type=int,
        default=5,
        help="Duration of the recording in seconds.",
    )
    parser.add_argument(
        "-i",
        "--interval",
        type=float,
        default=10.0,
        help="Time interval between recordings in seconds.",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="cpu",
        help="Device for running inference.",
    )
    parser.add_argument(
        "--backbone",
        default="whisper",
        help="backbone to use for audio processing. Options: whisper, vosk",
        choices=["whisper", "vosk"],
    )
    parser.add_argument(
        "--model-path",
        type=str,
        help="path to the model files, if not given, the pretrained model will be downloaded",
        default=None,
    )
    parser.add_argument(
        "--model-name",
        type=str,
        help="Specific name for Whisper model",
        choices=f"Available models name: ['tiny.en', 'tiny', 'base.en', 'base', 'small.en', 'small', 'medium.en', 'medium', 'large-v1', 'large-v2', 'large']",
        default=None,
    )
    parser.add_argument(
        "--language",
        type=str,
        help="Language for the model",
    )
    parser.add_argument(
        "--download-dir",
        type=str,
        help="Path to the directory where the model will be downloaded",
    )
    args = parser.parse_args()

    main(
        backbone=args.backbone,
        duration=args.duration,
        interval=args.interval,
        model_path=args.download_dir,
        model_name=args.model_name,
        language=args.language,
        download_dir=args.download_dir,
        device=args.device,
    )
