raise Exception("Fix errors with dataset first")

from Decorators import memoize_to_disk
from sent_feats_for_stacking import *
from load_data import load_process_essays, extract_features

from featurevectorizer import FeatureVectorizer
from featureextractionfunctions import *
from CrossValidation import cross_validation
from wordtagginghelper import *
from IterableFP import flatten
from DictionaryHelper import tally_items
from predictions_to_file import predictions_to_file
from results_procesor import ResultsProcessor
from argument_hasher import argument_hasher
# Classifiers
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.svm import LinearSVC
from sklearn.svm import SVC
from sklearn.lda import LDA

from window_based_tagger_config import get_config
# END Classifiers

import Settings
import logging
logging.basicConfig(format='%(asctime)s : %(levelname)s : %(message)s', level=logging.INFO)
logger = logging.getLogger()

# Create persister (mongo client) - fail fast if mongo service not initialized
processor = ResultsProcessor()

# not hashed as don't affect persistence of feature processing
SPARSE_WD_FEATS     = True
SPARSE_SENT_FEATS   = True

MIN_FEAT_FREQ       = 5        # 5 best so far
CV_FOLDS            = 5

MIN_TAG_FREQ        = 3
MIN_POWERSET_FREQ   = 1
LOOK_BACK           = 0     # how many sentences to look back when predicting tags
# end not hashed

# construct unique key using settings for pickling

settings = Settings.Settings()

root_folder = settings.data_directory + "CoralBleaching/Thesis_Dataset/"
folder =                            root_folder + "Training/"
processed_essay_filename_prefix =   root_folder + "Pickled/essays_proc_pickled_"
features_filename_prefix =          root_folder + "Pickled/feats_pickled_"
config = get_config(folder)

""" FEATURE EXTRACTION """
config["window_size"] = 9
offset = (config["window_size"] - 1) / 2

unigram_bow_window = fact_extract_bow_ngram_features(offset, 1)
unigram_window_stemmed = fact_extract_positional_word_features_stemmed(offset)
biigram_window_stemmed = fact_extract_ngram_features_stemmed(offset, 2)
trigram_window_stemmed = fact_extract_ngram_features_stemmed(offset, 3)

extractors = [unigram_bow_window,
              unigram_window_stemmed,
              biigram_window_stemmed,
              trigram_window_stemmed,
              extract_brown_cluster,
              extract_dependency_relation
]

feat_config = dict(config.items() + [("extractors", extractors)])

""" LOAD DATA """
mem_process_essays = memoize_to_disk(filename_prefix=processed_essay_filename_prefix)(load_process_essays)
tagged_essays = mem_process_essays( **config )
logger.info("Essays loaded")
# most params below exist ONLY for the purposes of the hashing to and from disk
mem_extract_features = memoize_to_disk(filename_prefix=features_filename_prefix)(extract_features)
essay_feats = mem_extract_features(tagged_essays, **feat_config)
logger.info("Features loaded")


""" DEFINE TAGS """
_, lst_all_tags = flatten_to_wordlevel_feat_tags(essay_feats)
regular_tags = list(set((t for t in flatten(lst_all_tags) if t[0].isdigit())))

""" works best with all the pair-wise causal relation codes """
wd_train_tags = regular_tags
wd_test_tags  = regular_tags

# tags to evaluate against

""" CLASSIFIERS """
""" Log Reg + Log Reg is best!!! """
fn_create_wd_cls = lambda: LogisticRegression() # C=1, dual = False seems optimal
#fn_create_wd_cls    = lambda : LinearSVC(C=1.0)

f_output_file = open(out_predictions_file, "w+")
f_output_file.write("Essay|Sent Number|Processed Sentence|Concept Codes|Predictions\n")

# Gather metrics per fold
cv_wd_td_ys_by_tag, cv_wd_td_predictions_by_tag = defaultdict(list), defaultdict(list)
cv_wd_vd_ys_by_tag, cv_wd_vd_predictions_by_tag = defaultdict(list), defaultdict(list)

folds = cross_validation(essay_feats, CV_FOLDS)
#TODO Parallelize
for i,(essays_TD, essays_VD) in enumerate(folds):

    # TD and VD are lists of Essay objects. The sentences are lists
    # of featureextractortransformer.Word objects
    print "\nFold %s" % i
    print "Training Tagging Model"
    """ Data Partitioning and Training """
    td_feats, td_tags = flatten_to_wordlevel_feat_tags(essays_TD)
    vd_feats, vd_tags = flatten_to_wordlevel_feat_tags(essays_VD)

    feature_transformer = FeatureVectorizer(min_feature_freq=MIN_FEAT_FREQ, sparse=SPARSE_WD_FEATS)
    td_X, vd_X = feature_transformer.fit_transform(td_feats), feature_transformer.transform(vd_feats)

    wd_td_ys_by_code = get_wordlevel_ys_by_code(td_tags, wd_train_tags)
    wd_vd_ys_by_code = get_wordlevel_ys_by_code(vd_tags, wd_train_tags)

    wd_td_ys_label_powersets = get_wordlevel_ys_by_labelpowerset(td_tags, wd_train_tags, MIN_POWERSET_FREQ)
    wd_vd_ys_label_powersets = get_wordlevel_ys_by_labelpowerset(vd_tags, wd_train_tags, MIN_POWERSET_FREQ)

    """ TRAIN Tagger """
    tag2word_classifier = train_classifier_per_code(td_X, wd_td_ys_label_powersets, fn_create_wd_cls)

    """ TEST Tagger """
    td_wd_predictions_by_label_powerset = test_classifier_per_code(td_X, tag2word_classifier)
    vd_wd_predictions_by_label_powerset = test_classifier_per_code(vd_X, tag2word_classifier)

    td_wd_predictions_by_code = \
        get_wordlevel_predictions_by_code_from_powerset_predictions(td_wd_predictions_by_label_powerset, wd_train_tags)

    vd_wd_predictions_by_code = \
        get_wordlevel_predictions_by_code_from_powerset_predictions(vd_wd_predictions_by_label_powerset, wd_train_tags)

    merge_dictionaries(wd_td_ys_by_code, cv_wd_td_ys_by_tag)
    merge_dictionaries(wd_vd_ys_by_code, cv_wd_vd_ys_by_tag)
    merge_dictionaries(td_wd_predictions_by_code, cv_wd_td_predictions_by_tag)
    merge_dictionaries(vd_wd_predictions_by_code, cv_wd_vd_predictions_by_tag)

f_output_file.close()
# print results for each code

""" Persist Results to Mongo DB """

wd_algo   = str(fn_create_wd_cls())

CB_TAGGING_TD, CB_TAGGING_VD, CB_SENT_TD, CB_SENT_VD = "CB_TAGGING_TD", "CB_TAGGING_VD", "CB_SENT_TD", "CB_SENT_VD"
parameters = dict(config)
parameters["extractors"] = map(lambda fn: fn.func_name, extractors)
parameters["min_feat_freq"] = MIN_FEAT_FREQ
parameters["min_powerset_freq"] = MIN_POWERSET_FREQ

wd_td_objectid = processor.persist_results(CB_TAGGING_TD, cv_wd_td_ys_by_tag, cv_wd_td_predictions_by_tag, parameters, wd_algo)
wd_vd_objectid = processor.persist_results(CB_TAGGING_VD, cv_wd_vd_ys_by_tag, cv_wd_vd_predictions_by_tag, parameters, wd_algo)

print processor.results_to_string(wd_td_objectid,   CB_TAGGING_TD,  wd_vd_objectid,     CB_TAGGING_VD,  "TAGGING")

