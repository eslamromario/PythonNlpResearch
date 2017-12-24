# coding: utf-8
import datetime
import logging
import dill
import pymongo

from collections import defaultdict
from typing import Any, List

from sklearn.linear_model import LogisticRegression
from sklearn.base import BaseEstimator

from CrossValidation import cross_validation
from Settings import Settings
from load_data import load_process_essays
from results_procesor import ResultsProcessor, __MICRO_F1__
from searn_parser_template_features import SearnModelTemplateFeaturesCostSensitive
from template_feature_extractor import NonLocalTemplateFeatureExtractor, NgramExtractor
from template_feature_extractor import single_words, word_pairs, three_words, word_distance, valency, unigrams, \
    between_word_features
from window_based_tagger_config import get_config
from wordtagginghelper import merge_dictionaries

client = pymongo.MongoClient()
db = client.metrics

CV_FOLDS = 5
DEV_SPLIT = 0.1

settings = Settings()
root_folder = settings.data_directory + "CoralBleaching/Thesis_Dataset/"
training_folder = root_folder + "Training" + "/"
test_folder = root_folder + "Test" + "/"
training_pickled = settings.data_directory + "CoralBleaching/Thesis_Dataset/training.pl"
# NOTE: These predictions are generated from the "./notebooks/SEARN/Keras - Train Tagger and Save CV Predictions For Word Tags.ipynb" notebook
# used as inputs to parsing model
rnn_predictions_folder = root_folder + "Predictions/Bi-LSTM-4-SEARN/"

config = get_config(training_folder)
processor = ResultsProcessor()

# Get Test Data In Order to Get Test CRELS
# load the test essays to make sure we compute metrics over the test CR labels
test_config = get_config(test_folder)
tagged_essays_test = load_process_essays(**test_config)
########################################################

fname = rnn_predictions_folder + "essays_train_bi_directional-True_hidden_size-256_merge_mode-sum_num_rnns-2_use_pretrained_embedding-True.dill"
with open(fname, "rb") as f:
    pred_tagged_essays = dill.load(f)

print("Number of pred tagged essasy %i" % len(pred_tagged_essays) ) # should be 902
print("Started at: " + str(datetime.datetime.now()))
logging.basicConfig(format='%(asctime)s : %(levelname)s : %(message)s', level=logging.INFO)
logger = logging.getLogger()

# In[7]:

CAUSER = "Causer"
RESULT = "Result"
EXPLICIT = "explicit"
CAUSER_EXPLICIT = "Causer_Explicit"
EXPLICIT_RESULT = "Explicit_Result"
CAUSER_EXPLICIT_RESULT = "Causer_Explicit_Result"
CAUSER_RESULT = "Causer_Result"

stag_freq = defaultdict(int)
unique_words = set()
for essay in pred_tagged_essays:
    for sentence in essay.sentences:
        for word, tags in sentence:
            unique_words.add(word)
            for tag in tags:
                stag_freq[tag] += 1

for essay in tagged_essays_test:
    for sentence in essay.sentences:
        for word, tags in sentence:
            unique_words.add(word)
            for tag in tags:
                stag_freq[tag] += 1

# TODO - don't ignore Anaphor, other and rhetoricals here
cr_tags = list((t for t in stag_freq.keys() if ( "->" in t) and
                not "Anaphor" in t and
                not "other" in t and
                not "rhetorical" in t and
                not "factor" in t and
                1==1
               ))

#Change to include explicit
regular_tags = set((t for t in stag_freq.keys() if ( "->" not in t) and (t == "explicit" or t[0].isdigit())))
vtags = set(regular_tags)

assert "explicit" in vtags, "explicit should be in the regular tags"

from parser_feature_extractor import FeatureExtractor, bag_of_word_extractor, bag_of_word_plus_tag_extractor

feat_extractor = FeatureExtractor([
    bag_of_word_extractor,
    bag_of_word_plus_tag_extractor,
])

folds = cross_validation(pred_tagged_essays, CV_FOLDS)
all_extractors = [
    single_words, word_pairs, three_words, word_distance,
    valency, unigrams,
    between_word_features]

def evaluate_features(  extractor_names: List[str], beta_decay: float = 0.3,
                        base_learner: Any=LogisticRegression, ngrams:int=2):

    extractors = [fn for fn in all_extractors if fn.__name__ in extractor_names]
    # Ensure all extractors located
    assert len(extractors) == len(extractor_names)

    template_feature_extractor = NonLocalTemplateFeatureExtractor(extractors=extractors)
    ngram_extractor = NgramExtractor(max_ngram_len=ngrams)

    sent_algo = "Shift_Reduce_Parser_LR"
    parameters = dict(config)
    parameters["extractors"] = extractor_names
    parameters["beta_decay"] = beta_decay
    parameters["no_stacking"] = True
    parameters["algorithm"] = str(base_learner)
    parameters["ngrams"]    = str(ngrams)

    cv_sent_td_ys_by_tag, cv_sent_td_predictions_by_tag = defaultdict(list), defaultdict(list)
    cv_sent_vd_ys_by_tag, cv_sent_vd_predictions_by_tag = defaultdict(list), defaultdict(list)

    #TODO - try to parallelize - pass in an array of func names (strings) - and look up real functions due to joblib limitations
    for i, (essays_TD, essays_VD) in enumerate(folds):
        print("\nCV % i" % i)
        parse_model = SearnModelTemplateFeaturesCostSensitive(feature_extractor=template_feature_extractor,
                                                              ngram_extractor=ngram_extractor, cr_tags=cr_tags,
                                                              base_learner_fact=base_learner,
                                                              beta_decay_fn=lambda beta: beta - beta_decay)
        parse_model.train(essays_TD, 12)

        sent_td_ys_bycode = parse_model.get_label_data(essays_TD)
        sent_vd_ys_bycode = parse_model.get_label_data(essays_VD)

        sent_td_pred_ys_bycode = parse_model.predict(essays_TD)
        sent_vd_pred_ys_bycode = parse_model.predict(essays_VD)

        merge_dictionaries(sent_td_ys_bycode, cv_sent_td_ys_by_tag)
        merge_dictionaries(sent_vd_ys_bycode, cv_sent_vd_ys_by_tag)
        merge_dictionaries(sent_td_pred_ys_bycode, cv_sent_td_predictions_by_tag)
        merge_dictionaries(sent_vd_pred_ys_bycode, cv_sent_vd_predictions_by_tag)
        # break

    CB_SENT_TD, CB_SENT_VD = "CR_CB_SHIFT_REDUCE_PARSER_TEMPLATED_FEATURE_SEL_TD", "CR_CB_SHIFT_REDUCE_PARSER_TEMPLATED_FEATURE_SEL_VD"

    sent_td_objectid = processor.persist_results(CB_SENT_TD, cv_sent_td_ys_by_tag,
                                                 cv_sent_td_predictions_by_tag, parameters, sent_algo)
    sent_vd_objectid = processor.persist_results(CB_SENT_VD, cv_sent_vd_ys_by_tag,
                                                 cv_sent_vd_predictions_by_tag, parameters, sent_algo)

    #print(processor.results_to_string(sent_td_objectid, CB_SENT_TD, sent_vd_objectid, CB_SENT_VD, "SENTENCE"))
    micro_f1 = float(processor.get_metric(CB_SENT_VD, sent_vd_objectid, __MICRO_F1__)["f1_score"])
    return micro_f1

BETA_DECAY = 0.3
#for ngrams in [1,2,3]:
for ngrams in [2]:

    feature_extractors = all_extractors[::]

    extractor_names = list(map(lambda fn: fn.__name__, feature_extractors))
    print("\tExtractors: {extractors}".format(extractors=",".join(extractor_names)))

    # RUN feature evaluation
    micro_f1 = evaluate_features(extractor_names=extractor_names, ngrams=ngrams, base_learner=LogisticRegression)

    print("\tMicro F1: {micro_f1}".format(micro_f1=micro_f1))

## TODO
#- Need to handle relations where same code -> same code

#-TODO - Neat Ideas
# Inject a random action (unform distribution) with a specified probability during training also
    # Ensures better exploration of the policy space. Initial algo predictions will be random but converges very quickly so this may be lost

#TODO Issues
# 1. Unsupported relations
# 2. Tagging model needs to tag causer:num and result:num too as tags, as well as explicits
# 3. Can't handle same tag to same tag
# 4. Can't handle same relation in both directions (e.g. if code is repeated)

#TODO - cost sensitive classification
# Look into this library if XGBoost doesn't work out - http://nbviewer.jupyter.org/github/albahnsen/CostSensitiveClassification/blob/master/doc/tutorials/tutorial_edcs_credit_scoring.ipynb

