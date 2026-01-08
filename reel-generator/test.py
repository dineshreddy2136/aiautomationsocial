
import torchaudio as ta
import torch
import functools
import soundfile as sf
import numpy as np
from chatterbox.mtl_tts import ChatterboxMultilingualTTS

def apply_patches():
    """
    Applies necessary patches for Mac/Python 3.14 compatibility.
    """
    print("Applying environment compatibility patches...")
    
    # Patch 1: torch.load
    # This is required because the model checkpoint was saved on a Linux/CUDA machine
    # and we are loading it on Mac (MPS/CPU).
    original_load = torch.load
    @functools.wraps(original_load)
    def safe_load(*args, **kwargs):
        if 'map_location' not in kwargs:
            kwargs['map_location'] = torch.device('cpu')
        return original_load(*args, **kwargs)
    torch.load = safe_load

# Apply environment patches
apply_patches()

# Determine device
device = "mps" if torch.backends.mps.is_available() else "cpu"
print(f"Using device: {device}")

# --- Test Code ---

# Multilingual examples
print("Loading Multilingual Model...")
try:
    multilingual_model = ChatterboxMultilingualTTS.from_pretrained(device=device)
    
    # English Test
    print("Generating English...")
    text = "This little girl used to write all her sorrows in a diary, but her parents would secretly read it. That is how they found out that someone was bullying her at school. Strangely, the very next day, that bullying classmate changed schools. One day, a man met her and warned her to be careful about her parents. Suspicious, she went to check a room. After entering through the window, she realized it was a boy's room. She found a photo there, but when her mom came, she acted like she was taking a shower and escaped. When she went to ask her grandmother about this, she got very worried. The girl wrote her feelings in the diary again. Reading that, the parents learned a truth... it wasn't this girl who killed her friend, but that bald girl was the real criminal. The very next day, a message came that the bald girl had gone missing. Subscribe for more videos."
    # ISO code for English is 'en'
    # Use the voice from clone.mp3
    wav = multilingual_model.generate(text, language_id="en", audio_prompt_path="nikhil.mp3")
    
    # Save using soundfile (more robust than torchaudio on some platforms)
    # wav is (1, T), convert to (T,) numpy array
    wav_numpy = wav.squeeze(0).detach().cpu().numpy()
    
    print(f"Saving to test-english.wav (SR: {multilingual_model.sr})")
    sf.write("test-english.wav", wav_numpy, multilingual_model.sr)
    print("Saved test-english.wav successfully!")
    
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"Multilingual generation failed: {e}")