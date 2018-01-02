# coding: utf-8
import numpy as np
import pymongo
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from collections import defaultdict
import dill
import datetime, logging

from CrossValidation import cross_validation
from load_data import load_process_essays
from searn_parser_costcla import SearnModelCla
from searn_parser_sklearn_weighted import SearnModelSklearnWeighted
from searn_parser_template_features import SearnModelTemplateFeaturesCostSensitive
from template_feature_extractor import NonLocalTemplateFeatureExtractor, NgramExtractor, third_order, label_set
from window_based_tagger_config import get_config
from searn_parser import SearnModel
#from searn_parser_xgboost import SearnModelXgBoost
from results_procesor import ResultsProcessor
from Settings import Settings
from wordtagginghelper import merge_dictionaries
import costcla
from costcla.models import CostSensitiveRandomForestClassifier, CostSensitiveLogisticRegression
from template_feature_extractor import single_words, word_pairs, three_words, word_distance, valency, unigrams, between_word_features

client = pymongo.MongoClient()
db = client.metrics

CV_FOLDS = 5
DEV_SPLIT = 0.1
NGRAMS = 2
MIN_FEAT_FREQ = 5

settings = Settings()
root_folder = settings.data_directory + "CoralBleaching/Thesis_Dataset/"
training_folder = root_folder + "Training" + "/"
test_folder = root_folder + "Test" + "/"
training_pickled = settings.data_directory + "CoralBleaching/Thesis_Dataset/training.pl"
# NOTE: These predictions are generated from the "./notebooks/SEARN/Keras - Train Tagger and Save CV Predictions For Word Tags.ipynb" notebook
predictions_folder = root_folder + "Predictions/Bi-LSTM-4-SEARN/"

config = get_config(training_folder)
processor = ResultsProcessor(dbname="metrics_causal")

# Get Test Data In Order to Get Test CRELS
# load the test essays to make sure we compute metrics over the test CR labels
test_config = get_config(test_folder)
tagged_essays_test = load_process_essays(**test_config)
########################################################

fname = predictions_folder + "essays_train_bi_directional-True_hidden_size-256_merge_mode-sum_num_rnns-2_use_pretrained_embedding-True.dill"
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

## Replace predicted tags with actual to test impact on recall
# With perfect tags and gold parse decisions, recall is 0.8417, F1 is 0.9140
# With best Predicted tags and gold parse decisions, recall is 0.8037, F1 is 0.8912
# With best Predicted tags and learned parse decisions, recall is 0.7545, F1 is 0.8449 (precision is ~0.96)
#
# for essay_ix, essay in enumerate(pred_tagged_essays):
#     act_tags = []
#     for sent_ix, taggged_sentence in enumerate(essay.sentences):
#         sent_tags = []
#         act_tags.append(sent_tags)
#         for wd, tags in taggged_sentence:
#             rtags = list(vtags.intersection([normalize(t) for t in tags]))
#             if len(rtags) == 0:
#                 sent_tags.append(EMPTY_TAG)
#             else:
#                 if len(rtags) > 1:
#                     rtags = [t for t in rtags if t != "explicit"]
#                 np.random.shuffle(rtags)
#                 sent_tags.append(rtags[0])
#
#     essay.pred_tagged_sentences = act_tags

cv_sent_td_ys_by_tag, cv_sent_td_predictions_by_tag = defaultdict(list), defaultdict(list)
cv_sent_vd_ys_by_tag, cv_sent_vd_predictions_by_tag = defaultdict(list), defaultdict(list)

folds = cross_validation(pred_tagged_essays, CV_FOLDS)
#TODO Parallelize

extractors = [single_words, word_pairs, three_words, word_distance, valency,
              unigrams, third_order, label_set,
              between_word_features]

template_feature_extractor = NonLocalTemplateFeatureExtractor(extractors=extractors)

ngram_extractor = NgramExtractor(max_ngram_len=NGRAMS)

for i,(essays_TD, essays_VD) in enumerate(folds):

    print("\nCV % i" % i)
    #parse_model = SearnModel(feat_extractor, cr_tags, base_learner_fact=LogisticRegression, beta_decay_fn=lambda beta: beta - 0.1)
    #parse_model = SearnModelXgBoost(feat_extractor, cr_tags, beta_decay_fn=lambda beta: beta - 0.3)
    #parse_model = SearnModelCla(feat_extractor, cr_tags, base_learner_fact=CostSensitiveLogisticRegression, beta_decay_fn=lambda beta: beta - 0.3)
    #parse_model = SearnModelSklearnWeighted(feat_extractor, cr_tags, base_learner_fact=LogisticRegression, beta_decay_fn=lambda beta: beta - 0.3)
    #parse_model = SearnModelSklearnWeighted(feat_extractor, cr_tags,
    #                                        base_learner_fact=lambda : RandomForestClassifier(n_jobs=1, max_depth=25), beta_decay_fn=lambda beta: beta - 0.3)
    # parse_model = SearnModelSklearnWeighted(feat_extractor, cr_tags,
    #                                        base_learner_fact=lambda : GradientBoostingClassifier(max_depth=3, max_features="log2"),
    #                                        beta_decay_fn=lambda beta: beta - 0.3, sparse=False)



    parse_model = SearnModelTemplateFeaturesCostSensitive(feature_extractor=template_feature_extractor, min_feature_freq=MIN_FEAT_FREQ,
                                                          ngram_extractor=ngram_extractor, cr_tags=cr_tags,
                                                          base_learner_fact=LogisticRegression, beta_decay_fn=lambda beta: beta - 0.3)
    parse_model.train(essays_TD, 12)

    sent_td_ys_bycode = parse_model.get_label_data(essays_TD)
    sent_vd_ys_bycode = parse_model.get_label_data(essays_VD)

    sent_td_pred_ys_bycode = parse_model.predict(essays_TD)
    sent_vd_pred_ys_bycode = parse_model.predict(essays_VD)

    merge_dictionaries(sent_td_ys_bycode, cv_sent_td_ys_by_tag)
    merge_dictionaries(sent_vd_ys_bycode, cv_sent_vd_ys_by_tag)
    merge_dictionaries(sent_td_pred_ys_bycode, cv_sent_td_predictions_by_tag)
    merge_dictionaries(sent_vd_pred_ys_bycode, cv_sent_vd_predictions_by_tag)
    #break

#CB_SENT_TD, CB_SENT_VD = "CR_CB_SHIFT_REDUCE_PARSER_TD" , "CR_CB_SHIFT_REDUCE_PARSER_VD"
CB_SENT_TD, CB_SENT_VD = "CR_CB_SHIFT_REDUCE_PARSER_TEMPLATED_TD" , "CR_CB_SHIFT_REDUCE_PARSER_TEMPLATED_VD"
#sent_algo = "Shift_Reduce_Parser"
sent_algo = "Shift_Reduce_Parser_LR"
#sent_algo = "Shift_Reduce_Parser_XGB_10"
#sent_algo = "Shift_Reduce_Parser_CLA_LR"
#sent_algo = "Shift_Reduce_Parser_WTD_LR"
#sent_algo = "Shift_Reduce_Parser_WTD_RF"
#sent_algo = "Shift_Reduce_Parser_WTD_RF_25"
#sent_algo = "Shift_Reduce_Parser_WTD_GBT_3"
parameters = dict(config)
parameters["extractors"] = list(map(lambda fn: fn.__name__, extractors))
parameters["ngrams"] = NGRAMS
parameters["no_stacking"] = True
parameters["min_feat_freq"] = MIN_FEAT_FREQ

sent_td_objectid = processor.persist_results(CB_SENT_TD, cv_sent_td_ys_by_tag, cv_sent_td_predictions_by_tag, parameters, sent_algo)
sent_vd_objectid = processor.persist_results(CB_SENT_VD, cv_sent_vd_ys_by_tag, cv_sent_vd_predictions_by_tag, parameters, sent_algo)

print(processor.results_to_string(sent_td_objectid, CB_SENT_TD,     sent_vd_objectid,   CB_SENT_VD,     "SENTENCE"))

## TODO
#- Re-train tagging model, adding tags where reg tag is missing but is included in a causer or result tag.
#- Also include explicit in the predicted tags.
#- Need to handle relations where same code -> same code

#-TODO - Neat Ideas
# Inject a random action (unform distribution) with a specified probability during training also
    # Ensures better exploration of the policy space. Initial algo predictions will be random but converges very quickly so this may be lost

#TODO * Need to make sure the tagger tags EXCPLICIT tags. These can then be skipped by the parser, but will be included in the features used to train the parser and taggger. Do we want to train a separate tagger that determines if a tagged word is a cause, explict or result. That will then resolve the direction of the relation?
#TODO - recall is v low on training data. Test it with perfect tagging predictions

#TODO Issues
# 1. Unsupported relations
# 2. Tagging model needs to tag causer:num and result:num too as tags, as well as explicits
# 3. Can't handle same tag to same tag
# 4. Can't handle same relation in both directions (e.g. if code is repeated)

#TODO - cost sensitive classification
# Look into this library if XGBoost doesn't work out - http://nbviewer.jupyter.org/github/albahnsen/CostSensitiveClassification/blob/master/doc/tutorials/tutorial_edcs_credit_scoring.ipynb

