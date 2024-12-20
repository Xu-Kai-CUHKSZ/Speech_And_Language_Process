import librosa
import soundfile
import numpy as np
from matplotlib import pyplot as plt
import scipy.signal as signal
import copy

sr = 16000 # Sample rate 采样率
n_fft = 1024 # fft points (samples)  希望提取的频率的组数--513
frame_shift = 0.0125 # 单位为秒
frame_length = 0.05 # 单位为秒，时间表示法
hop_length = int(sr*frame_shift) # 帧移，采样点表示法 
win_length = int(sr*frame_length) # 窗长
n_mels = 80 # Number of Mel banks to generate  梅尔谱频率组数 
power = 1.2 # Exponent for amplifying the predicted magnitude
n_iter = 100 # Number of inversion iterations
preemphasis = .97 # or None # 预加重参数
max_db = 100
ref_db = 20
top_db = 15


def get_spectrograms(fpath):
    '''Returns normalized log(melspectrogram) and log(magnitude) from `sound_file`.
    Args:
      sound_file: A string. The full path of a sound file.

    Returns:
      mel: A 2d array of shape (T, n_mels) <- Transposed
      mag: A 2d array of shape (T, 1+n_fft/2) <- Transposed
 '''
    # Loading sound file 读取语音信号波形
    # librosa 在读取时，可以改变采样率。这里被改为 22050
    # y-一维时域信号
    y, sr = librosa.load(fpath, sr=22050)
    plt.figure()
    plt.title("oringin: wavform")
    plt.plot(y)
    plt.show()
    
    # Trimming - 头尾静音消除 
    # 可以将 top_db 分贝（强度）以下的切掉
    y, _ = librosa.effects.trim(y, top_db=top_db)

    # Preemphasis 预加重（经典的信号处理算法）
    y = np.append(y[0], y[1:] - preemphasis * y[:-1])

    # stft 短时傅里叶变换变化
    # 得到 linear 是短时傅里叶谱，包含幅度和相位信息。linear 中每一个元素是复数 a+bj 。 可以通过取绝对值，将复数变为实数。  
    linear = librosa.stft(y=y,
                          n_fft=n_fft,
                          hop_length=hop_length,
                          win_length=win_length)

    # magnitude spectrogram 幅度谱
    # 通常将相位信息去掉，只保留幅度。 
    mag = np.abs(linear)  # (1+n_fft//2, T)

    # mel spectrogram 梅尔谱 
    # mel_basis 是梅尔谱矩阵，乘上幅度谱矩阵（mag），就可以得到梅尔谱
    mel_basis = librosa.filters.mel(sr, n_fft, n_mels)  # (n_mels, 1+n_fft//2)
    mel = np.dot(mel_basis, mag)  # (n_mels, t)

    # to decibel 取对数，将梅尔谱变为分贝单位 
    mel = 20 * np.log10(np.maximum(1e-5, mel))
    mag = 20 * np.log10(np.maximum(1e-5, mag))

    # normalize 
    mel = np.clip((mel - ref_db + max_db) / max_db, 1e-8, 1)
    mag = np.clip((mag - ref_db + max_db) / max_db, 1e-8, 1)

    # Transpose
    mel = mel.T.astype(np.float32)  # (T, n_mels)
    mag = mag.T.astype(np.float32)  # (T, 1+n_fft//2)

    return mel, mag

def melspectrogram2wav(mel):
    '''# Generate wave file from spectrogram'''
    # transpose
    mel = mel.T

    # de-noramlize 
    mel = (np.clip(mel, 0, 1) * max_db) - max_db + ref_db

    # to amplitude  /-----/  the reverse of # to decibel
    mel = np.power(10.0, mel * 0.05)
    m = _mel_to_linear_matrix(sr, n_fft, n_mels)
    mag = np.dot(m, mel)

    # wav reconstruction
    wav = griffin_lim(mag)

    # de-preemphasis
    wav = signal.lfilter([1], [1, -preemphasis], wav)

    # trim
    wav, _ = librosa.effects.trim(wav)

    return wav.astype(np.float32)


def spectrogram2wav(mag):
    '''# Generate wave file from spectrogram'''
    # transpose
    mag = mag.T

    # de-noramlize
    mag = (np.clip(mag, 0, 1) * max_db) - max_db + ref_db

    # to amplitude
    mag = np.power(10.0, mag * 0.05)

    # wav reconstruction
    wav = griffin_lim(mag)

    # de-preemphasis
    wav = signal.lfilter([1], [1, -preemphasis], wav)

    # c
    wav, _ = librosa.effects.trim(wav)

    return wav.astype(np.float32)



def _mel_to_linear_matrix(sr, n_fft, n_mels):
    m = librosa.filters.mel(sr, n_fft, n_mels)
    m_t = np.transpose(m)
    p = np.matmul(m, m_t)
    d = [1.0 / x if np.abs(x) > 1.0e-8 else x for x in np.sum(p, axis=0)]
    return np.matmul(m_t, np.diag(d))


def griffin_lim(spectrogram):
    '''Applies Griffin-Lim's raw.
    '''
    X_best = copy.deepcopy(spectrogram)
    for i in range(n_iter):
        X_t = invert_spectrogram(X_best)
        est = librosa.stft(X_t, n_fft, hop_length, win_length=win_length)
        phase = est / np.maximum(1e-8, np.abs(est))
        X_best = spectrogram * phase
    X_t = invert_spectrogram(X_best)
    y = np.real(X_t)

    return y


def invert_spectrogram(spectrogram):
    '''
    spectrogram: [f, t]
    '''
    return librosa.istft(spectrogram, hop_length, win_length=win_length, window="hann")

def plot_spectrogram_to_numpy(spectrogram):
    fig, ax = plt.subplots(figsize=(12, 3))
    im = ax.imshow(spectrogram, aspect="auto", origin="lower",
                   interpolation='none')
    plt.colorbar(im, ax=ax)
    plt.xlabel("Frames")
    plt.ylabel("Channels")
    plt.tight_layout()

    fig.canvas.draw()
    data = save_figure_to_numpy(fig)
    plt.close()
    return data

def save_figure_to_numpy(fig):
    # save it to a numpy array.
    data = np.fromstring(fig.canvas.tostring_rgb(), dtype=np.uint8, sep='')
    data = data.reshape(fig.canvas.get_width_height()[::-1] + (3,))
    return data


def test1(): 
    ## 给定一条语音
    p = './0001_000351.wav'
    aa = get_spectrograms(p)
    print("melspec size: {} , stft spec size:{}".format(aa[0].shape,aa[1].shape))
    # size : (frames, ndim)
    plt.figure()
    plt.title("oringin melspec & stft spec")
    plt.subplot(2, 1, 2)
    plt.imshow(plot_spectrogram_to_numpy(aa[1].T))
    plt.subplot(2, 1, 1)
    plt.imshow(plot_spectrogram_to_numpy(aa[0].T))
    plt.show()

    # wav = melspectrogram2wav(mel.T)
    wav1 = melspectrogram2wav(aa[0]) # input size : (frames ,ndim)
    plt.figure()
    plt.title("mel2wav: wavform")
    plt.plot(wav1)
    plt.show()
    # librosa.output.write_wav("gg_stft.wav", wav, sr)
    soundfile.write(p.replace('.w','_gff.w'), wav1, sr)
    print("finished change ")

    ###  画出 转化语音的谱
    aa = get_spectrograms(p.replace('.w','_gff.w'))
    plt.figure()
    plt.title("new wav  :  melspec & stft spec")
    plt.subplot(2, 1, 2)
    plt.imshow(plot_spectrogram_to_numpy(aa[1].T))
    plt.subplot(2, 1, 1)
    plt.imshow(plot_spectrogram_to_numpy(aa[0].T))
    plt.show()

    exit()


if __name__ == '__main__':
    test1() 
