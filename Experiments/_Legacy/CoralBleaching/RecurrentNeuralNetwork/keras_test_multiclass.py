from __future__ import absolute_import
from __future__ import print_function

import numpy as np
from collections import defaultdict
from keras.preprocessing import sequence
from keras.optimizers import SGD, RMSprop, Adagrad
from keras.utils import np_utils
import keras.layers.convolutional
from keras.models import Sequential
from keras.layers.core import Dense, Dropout, Activation
from keras.layers.embeddings import Embedding
from keras.layers.recurrent import LSTM, GRU, JZS1

from Metrics import rpf1

'''
    Train a LSTM on the IMDB sentiment classification task.

    The dataset is actually too small for LSTM to be of any advantage
    compared to simpler, much faster methods such as TF-IDF+LogReg.

    Notes:

    - RNNs are tricky. Choice of batch size is important,
    choice of loss and optimizer is critical, etc.
    Most configurations won't converge.

    - LSTM loss decrease during training can be quite different
    from what you see with CNNs/MLPs/etc. It's more or less a sigmoid
    instead of an inverse exponential.

    GPU command:
        THEANO_FLAGS=mode=FAST_RUN,device=gpu,floatX=float32 python imdb_lstm.py

    250s/epoch on GPU (GT 650M), vs. 400s/epoch on CPU (2.4Ghz Core i7).
'''
from Decorators import memoize_to_disk
from load_data import load_process_essays

from window_based_tagger_config import get_config
from IdGenerator import IdGenerator as idGen
# END Classifiers

import Settings
import logging

import datetime
print("Started at: " + str(datetime.datetime.now()))

logging.basicConfig(format='%(asctime)s : %(levelname)s : %(message)s', level=logging.INFO)
logger = logging.getLogger()

TEST_SPLIT          = 0.2
PRE_PEND_PREV_SENT  = 0 #2 seems good
REVERSE             = False
PREPEND_REVERSE     = False

# end not hashed

# construct unique key using settings for pickling

settings = Settings.Settings()
folder =                            settings.data_directory + "CoralBleaching/BrattData/EBA1415_Merged/"
processed_essay_filename_prefix =   settings.data_directory + "CoralBleaching/BrattData/Pickled/essays_proc_pickled_"

config = get_config(folder)
config["stem"] = True

""" FEATURE EXTRACTION """
""" LOAD DATA """
mem_process_essays = memoize_to_disk(filename_prefix=processed_essay_filename_prefix)(load_process_essays)
tagged_essays = mem_process_essays( **config )

generator = idGen()
generator.get_id("......")
xs = []
ys = []
END_TAG = 'END'

# cut texts after this number of words (among top max_features most common words)
maxlen = 0

tag_freq = defaultdict(int)
for essay in tagged_essays:
    for sentence in essay.sentences:
        for word, tags in sentence:
            for tag in tags:
                if (tag[-1].isdigit() or tag in {"Causer", "explicit", "Result"} \
                        or tag.startswith("Causer") or tag.startswith("Result") or tag.startswith("explicit"))\
                        and not ("Anaphor" in tag or "rhetorical" in tag or "other" in tag or "->" in tag):
                #if not ("Anaphor" in tag or "rhetorical" in tag or "other" in tag):
                    tag_freq[tag] += 1

freq_tags = set((tag for tag, freq in tag_freq.items() if freq >= 20))

lst_freq_tags = sorted(freq_tags)
ix2tag = {}
for i, tag in enumerate(lst_freq_tags):
    ix2tag[i] = tag


from numpy.random import shuffle
shuffle(tagged_essays)

for essay in tagged_essays:
    sent_rows = [[generator.get_id(END_TAG)] for i in range(PRE_PEND_PREV_SENT)]
    for sentence in essay.sentences:
        row = []

        un_tags = set()
        for word, tags in sentence + [(END_TAG, set())]:
            id = generator.get_id(word)
            row.append(id)
            for tag in tags:
                un_tags.add(tag)

        y = []
        for tag in lst_freq_tags:
            y.append(1 if tag in un_tags else 0)

        sent_rows.append(row)
        ys.append(y)

        if PRE_PEND_PREV_SENT > 0:
            x = []
            for i in range(PRE_PEND_PREV_SENT + 1):
                ix = i+1
                if ix > len(sent_rows):
                    break
                x = sent_rows[-ix] + x
            row = x

        if PREPEND_REVERSE:
            row = row[::-1] + row
        xs.append(row)
        maxlen = max(len(xs[-1]), maxlen)
max_features=generator.max_id() + 2
batch_size = 16

print("Loading data...")
num_training = int((1.0 - TEST_SPLIT) * len(xs))
num_left = len(xs) - num_training
#num_valid = int(num_left / 2.0)
num_valid = 0
num_test = len(xs) - num_training - num_valid

MAX_LEN = maxlen
print("Pad sequences (samples x time)")
xs = sequence.pad_sequences(xs, maxlen=MAX_LEN)

X_train, y_train, X_valid, y_valid, X_test, y_test = \
    xs[:num_training], ys[:num_training],  \
    xs[num_training:num_training + num_valid], ys[num_training:num_training + num_valid],  \
    xs[num_training + num_valid:], ys[num_training + num_valid:]

print(X_train.shape, 'train sequences')
print(X_valid.shape, 'valid sequences')
print(X_test.shape,  'test sequences')

embedding_size = 64

print('Build model...')
model = Sequential()
model.add(Embedding(max_features, embedding_size, mask_zero=True))
#model.add(LSTM(embedding_size, 128)) # try using a GRU instead, for fun
#model.add(GRU(embedding_size, embedding_size)) # try using a GRU instead, for fun
#model.add(JZS1(embedding_size, 64, return_sequences=True)) # try using a GRU instead, for fun
model.add(JZS1(embedding_size, 64)) # try using a GRU instead, for fun
#JSZ1, embedding = 64, 64 hidden = 0.708
#model.add(Dropout(0.2))
#model.add(Dropout(0.25))
#model.add(Dense(64, 64))
#model.add(Dropout(0.25))
model.add(Dense(64, len(lst_freq_tags)))
model.add(Activation('sigmoid'))

# try using different optimizers and different optimizer configs
model.compile(loss='binary_crossentropy', optimizer='adam', class_mode="binary")

# Does very well (F1 0.684) using embedding 64 and hidden = 64

print("Train...")
last_accuracy = 0
iterations = 0
decreases = 0

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
y_train, y_valid, y_test = np.asarray(y_train), np.asarray(y_valid), np.asarray(y_test)

def test(epochs = 1):
    results = model.fit(X_train, y_train, batch_size=batch_size, nb_epoch=epochs, validation_split=0.0, show_accuracy=True, verbose=1)
    #valid_probs = model.predict_proba(X_valid, batch_size=batch_size)
    test_probs  = model.predict_proba(X_test,  batch_size=batch_size)
    valid_f1s = []
    test_f1s = []
    test_f1s_50 = []
    cutoff = 0
    for ix, tag in ix2tag.items():
        #valid_tag_predictions = valid_probs[:, ix]
        test_tag_predictions  = test_probs[:, ix]

        #valid_tag_ys = y_valid[:, ix]
        test_tag_ys  =  y_test[:, ix]

        #r_v, p_v, f1_v, cutoff = find_cutoff(valid_tag_ys, valid_tag_predictions)
        #alid_f1s.append(f1_v)

        #test_classes =      [1 if p >= cutoff else 0 for p in test_tag_predictions]
        test_classes_5050 = [1 if p >= 0.5 else 0 for p in test_tag_predictions]

        #r, p, f1 = rpf1(test_tag_ys, test_classes)
        r50, p50, f150 = rpf1(test_tag_ys, test_classes_5050)
        #print("VALIDATION:", tag.ljust(35), str(sum(valid_tag_ys)).ljust(3), "recall", rnd(r_v), "precision", rnd(p_v), "f1", rnd(f1_v), "cutoff", rnd(cutoff))
        #print("TEST      :", tag.ljust(35), str(sum(test_tag_ys)).ljust(3),  "recall", rnd(r),   "precision", rnd(p),   "f1", rnd(f1),   "cutoff", rnd(cutoff))
        print("TEST 50/50:", tag.ljust(35), str(sum(test_tag_ys)).ljust(3),  "recall", rnd(r50),   "precision", rnd(p50),   "f1", rnd(f150),   "cutoff", rnd(cutoff))

        #test_f1s.append(f1)
        test_f1s_50.append(f150)

    #print("MEAN VALID F1       : " + str(np.mean(valid_f1s)))
    #print("MEAN TEST  F1       : " + str(np.mean(test_f1s)))
    print("MEAN TEST  F1 50/50 : " + str(np.mean(test_f1s_50)))
    return np.mean(test_f1s), np.mean(test_f1s_50)

best = 0
best_5050 = 0
while True:
    iterations += 1

    accuracy, accuracy_5050 = test(1)
    #best = max(best, accuracy)
    new_best = accuracy_5050 > best
    best_5050 = max(best_5050, accuracy_5050)
    if accuracy < last_accuracy:
        decreases +=1
    else:
        decreases = 0

    #print("Best F1      : ", best)
    if new_best:
        print("*** NEW Best F1 50/50: ", best_5050, "****")
    else:
        print("Best F1 50/50: ", best_5050)
    if decreases >= 30 and iterations > 10:
        print("Val Loss increased from %f to %f. Stopping" % (last_accuracy, accuracy))
        break
    last_accuracy = accuracy

#results = model.fit(X_train, y_train, batch_size=batch_size, nb_epoch=  5, validation_split=0.2, show_accuracy=True, verbose=1)
print("at: " + str(datetime.datetime.now()))

# Causer: recall 0.746835443038 precision 0.670454545455 f1 0.706586826347 - 32 embedding, lstm, sigmoid, adam
