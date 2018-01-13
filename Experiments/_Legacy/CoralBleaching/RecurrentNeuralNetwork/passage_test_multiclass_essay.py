from Metrics import rpf1
from Decorators import memoize_to_disk
from load_data import load_process_essays
from IterableFP import flatten

from window_based_tagger_config import get_config
from IdGenerator import IdGenerator as idGen
import numpy as np
# END Classifiers

import Settings
import logging

from collections import defaultdict
import datetime
print("Started at: " + str(datetime.datetime.now()))

logging.basicConfig(format='%(asctime)s : %(levelname)s : %(message)s', level=logging.INFO)
logger = logging.getLogger()

MIN_WORD_FREQ       = 2        # 5 best so far
#TARGET_Y            = "explicit"
TEST_SPLIT          = 0.2
PRE_PEND_PREV_SENT  = 3 #2 seems good
REVERSE             = False
PREPEND_REVERSE     = False
# end not hashed

# construct unique key using settings for pickling

settings = Settings.Settings()
folder =                            settings.data_directory + "CoralBleaching/BrattData/EBA1415_Merged/"
processed_essay_filename_prefix =   settings.data_directory + "CoralBleaching/BrattData/Pickled/essays_proc_pickled_"

config = get_config(folder)

""" FEATURE EXTRACTION """
""" LOAD DATA """
mem_process_essays = memoize_to_disk(filename_prefix=processed_essay_filename_prefix)(load_process_essays)
tagged_essays = mem_process_essays( **config )

generator = idGen()
xs = []
ys = []
END_TAG = 'END'

# cut texts after this number of words (among top max_features most common words)
maxlen = 0

all_tags = set()
tag_freq = defaultdict(int)
for essay in tagged_essays:
    for sentence in essay.sentences:
        for word, tags in sentence:
            for tag in tags:
                #if tag.isdigit() or tag in {"Causer", "explicit", "Result"}:
                #    all_tags.add(tag)
                tag_freq[tag] +=1

freq_tags = set((tag for tag, freq in tag_freq.items() if freq >= 10
                 and "other" not in tag and "Anaphor" not in tag and "rhetorical" not in tag
                 and "compiled" not in tag.lower()))

lst_freq_tags = sorted(freq_tags)
ix2tag = {}
for i, tag in enumerate(lst_freq_tags):
    ix2tag[i] = tag

for essay in tagged_essays:

    un_tags = set()
    row = []
    for sentence in essay.sentences:

        for word, tags in sentence + [(END_TAG, set())]:
            id = generator.get_id(word)
            row.append(id)
            for tag in tags:
                un_tags.add(tag)

    y = []
    for tag in lst_freq_tags:
        y.append(1 if tag in un_tags else 0)
    ys.append(y)

    if PREPEND_REVERSE:
        row = row[::-1] + row
    xs.append(row)
    maxlen = max(len(xs[-1]), maxlen)

from passage.layers import Embedding
from passage.layers import GatedRecurrent
from passage.layers import LstmRecurrent
from passage.layers import Dense

from passage.models import RNN
from passage.utils import save, load

print("Loading data...")
num_training = int((1.0 - 0.2) * len(xs))

X_train, y_train, X_test, y_test = xs[:num_training], ys[:num_training], xs[num_training:], ys[num_training:]

num_feats = generator.max_id() + 1

layers = [
    Embedding(size=128, n_features=num_feats),
    #LstmRecurrent(size=32),
    #NOTE - to use a deep RNN, you need all but the final layers with seq_ouput=True
    #GatedRecurrent(size=128, seq_output=True),
    #GatedRecurrent(size=256, direction= 'backward' if REVERSE else 'forward'),
    GatedRecurrent(size=128, seq_output=True),
    GatedRecurrent(size=128),
    #Dense(size=64, activation='sigmoid'),
    Dense(size=len(lst_freq_tags), activation='sigmoid'),
]

#emd 128, gru 32/64 is good - 0.70006 causer

print("Creating Model")
model = RNN(layers=layers, cost='bce')

def find_cutoff(y_test, predictions):
    scale = 20.0

    min_val = round(min(predictions))
    max_val = round(max(predictions))
    diff = max_val - min_val
    inc = diff / scale

    cutoff = -1
    best = -1
    for i in range(1, int(scale)+1, 1):
        val = inc * i
        classes = [1 if p >= val else 0 for p in predictions]
        r, p, f1 = rpf1(y_test, classes)
        if f1 >= best:
            cutoff = val
            best = f1

    classes = [1 if p >= cutoff else 0 for p in predictions]
    r, p, f1 = rpf1(y_test, classes)
    return r, p, f1, cutoff

def rnd(v):
    digits = 6
    return str(round(v, digits)).ljust(digits+2)
# convert to numpy array for slicing
y_train, y_test = np.asarray(y_train), np.asarray(y_test)

def test(epochs=1):
    model.fit(X_train, y_train, n_epochs=epochs, batch_size=64)#64 seems good for now
    predictions = model.predict(X_test)
    f1s = []
    for ix, tag in ix2tag.items():
        tag_predictions = predictions[:, ix]
        tag_ys = y_test[:, ix]
        r, p, f1, cutoff = find_cutoff(tag_ys, tag_predictions)
        print(tag.ljust(35), str(sum(tag_ys)).ljust(4),  "recall", rnd(r), "precision", rnd(p), "f1", rnd(f1), "cutoff", rnd(cutoff))
        f1s.append(f1)
    mean_f1 = np.mean(f1s)
    print("MEAN F1: " + str(mean_f1))
    return mean_f1

last_f1 = -1
decreases = 0
max_f1 = 0.0

while True:
    f1 = test(5)
    if f1 < last_f1:
        decreases += 1
    max_f1 = max(f1, max_f1)
    if decreases > 1000:
        print "Stopping, f1 %f is less than previous f1 %f" % (f1, last_f1)
        break
    last_f1 = f1

print "Max:", rnd(max_f1)
bp = 0
#save(model, 'save_test.pkl')
#model = load('save_test.pkl')

""" This model, although doing sequential prediction, predicts a tag per document not per word. """