import torch
import torchaudio
from transformers import WhisperForConditionalGeneration, WhisperProcessor


WHISPER_MODEL = None
WHISPER_PROCESSOR = None


def get_device() -> str:
    '''
    Returns the device to be used for inference. 
    If a GPU is available, it returns "cuda", otherwise it returns "cpu".
    '''

    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def get_whisper_model_and_processor(device: str):
    '''
    Returns the Whisper model and processor. 
    If they are not already loaded, it loads them and moves the model to the specified device.

    device: The device to move the model to ("cuda" or "cpu").
    returns: A tuple containing the Whisper model and processor.
    '''

    global WHISPER_MODEL, WHISPER_PROCESSOR
    if WHISPER_MODEL is None or WHISPER_PROCESSOR is None:
        WHISPER_MODEL = WhisperForConditionalGeneration.from_pretrained("openai/whisper-small").to(device)
        WHISPER_PROCESSOR = WhisperProcessor.from_pretrained("openai/whisper-small")
    return WHISPER_MODEL, WHISPER_PROCESSOR


def transcribe_audio(audio_path: str) -> str:
    '''
    Transcribes the audio file at the specified path using the Whisper model.
    The audio is processed in chunks to handle long audio files, 
    with a small overlap to ensure continuity between chunks. 
    The transcribed text from all chunks is concatenated and returned as a single string.    

    audio_path: The path to the audio file to be transcribed.
    returns: The transcribed text from the audio file.
    '''
    device = get_device()
    model, processor = get_whisper_model_and_processor(device)

    waveform, sample_rate = torchaudio.load(audio_path)
    if sample_rate != 16000:
        resampler = torchaudio.transforms.Resample(sample_rate, 16000)
        waveform = resampler(waveform)

    if waveform.shape[0] > 1:
        waveform = torch.mean(waveform, dim=0, keepdim=True)

    waveform = waveform[0].numpy()

    chunk_size = 30 * 16000
    overlap_size = 2 * 16000
    total_length = waveform.shape[0]
    num_chunks = (total_length + chunk_size - 1) // chunk_size
    all_text = []

    for i in range(num_chunks):
        start = max(0, i * chunk_size - overlap_size)
        end = min((i + 1) * chunk_size, total_length)
        chunk = waveform[start:end]

        inputs = processor(
            chunk,
            return_tensors="pt",
            sampling_rate=16000
        ).input_features.to(device)

        with torch.no_grad():
            generated_ids = model.generate(
                inputs,
                task = "transcribe",
                repetition_penalty=1.3,
            )

        text = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
        all_text.append(text)

    return " ".join(all_text)