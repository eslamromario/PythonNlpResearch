from Decorators import memoize_to_disk
from sent_feats_for_stacking import *
from load_data import load_process_essays, extract_features

from featureextractionfunctions import *
from CrossValidation import cross_validation
from wordtagginghelper import *
from IterableFP import flatten
from collections import defaultdict
from window_based_tagger_config import get_config
from results_procesor import ResultsProcessor, compute_metrics
from nltk.classify import maxent
# END Classifiers

import Settings
import logging

logging.basicConfig(format='%(asctime)s : %(levelname)s : %(message)s', level=logging.INFO)
logger = logging.getLogger()

# Create persister (mongo client) - fail fast if mongo service not initialized
processor = ResultsProcessor()

NUM_TRAIN_ITERATIONS = 5
# not hashed as don't affect persistence of feature processing
SPARSE_WD_FEATS     = True
SPARSE_SENT_FEATS   = True

MIN_FEAT_FREQ       = 5        # 5 best so far
CV_FOLDS            = 5

MIN_TAG_FREQ        = 5
LOOK_BACK           = 0     # how many sentences to look back when predicting tags
# end not hashed

# construct unique key using settings for pickling

settings = Settings.Settings()
folder =                            settings.data_directory + "CoralBleaching/BrattData/EBA1415_Merged/"
processed_essay_filename_prefix =   settings.data_directory + "CoralBleaching/BrattData/Pickled/essays_proc_pickled_"
features_filename_prefix =          settings.data_directory + "CoralBleaching/BrattData/Pickled/feats_pickled_"

out_metrics_file     =              settings.data_directory + "CoralBleaching/Results/metrics.txt"
out_predictions_file =              settings.data_directory + "CoralBleaching/Results/predictions.txt"

config = get_config(folder)

""" FEATURE EXTRACTION """
offset = (config["window_size"] - 1) / 2

unigram_window_stemmed = fact_extract_positional_word_features_stemmed(offset)
biigram_window_stemmed = fact_extract_ngram_features_stemmed(offset, 2)

#pos_tag_window = fact_extract_positional_POS_features(offset)
#pos_tag_plus_wd_window = fact_extract_positional_POS_features_plus_word(offset)
#head_wd_window = fact_extract_positional_head_word_features(offset)
#pos_dep_vecs = fact_extract_positional_dependency_vectors(offset)

extractors = [unigram_window_stemmed, biigram_window_stemmed]
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

CAUSE_TAGS = ["Causer", "Result", "explicit"]
CAUSAL_REL_TAGS = [CAUSAL_REL, CAUSE_RESULT, RESULT_REL]# + ["explicit"]

""" works best with all the pair-wise causal relation codes """
wd_train_tags = regular_tags + CAUSE_TAGS
wd_test_tags  = regular_tags + CAUSE_TAGS

# tags from tagging model used to train the stacked model
sent_input_feat_tags = wd_train_tags
# find interactions between these predicted tags from the word tagger to feed to the sentence tagger
sent_input_interaction_tags = wd_train_tags
# tags to train (as output) for the sentence based classifier
sent_output_train_test_tags = list(set(regular_tags + CAUSE_TAGS + CAUSAL_REL_TAGS))

assert set(CAUSE_TAGS).issubset(set(sent_input_feat_tags)), "To extract causal relations, we need Causer tags"
# tags to evaluate against

""" CLASSIFIERS """
""" Log Reg + Log Reg is best!!! """

f_output_file = open(out_predictions_file, "w+")
f_output_file.write("Essay|Sent Number|Processed Sentence|Concept Codes|Predictions\n")

# Gather metrics per fold
cv_wd_td_ys_by_tag, cv_wd_td_predictions_by_tag = defaultdict(list), defaultdict(list)
cv_wd_vd_ys_by_tag, cv_wd_vd_predictions_by_tag = defaultdict(list), defaultdict(list)

folds = cross_validation(essay_feats, CV_FOLDS)
def pad_str(val):
    return str(val).ljust(20) + "  "

def toDict(obj):
    return obj.__dict__

#TODO Parallelize
for i,(essays_TD, essays_VD) in enumerate(folds):

    # TD and VD are lists of Essay objects. The sentences are lists
    # of featureextractortransformer.Word objects
    print "\nFold %s" % i
    print "Training Tagging Model"
    """ Training """

    # Just get the tags (ys)
    td_feats, td_tags = flatten_to_wordlevel_feat_tags(essays_TD)
    vd_feats, vd_tags = flatten_to_wordlevel_feat_tags(essays_VD)

    wd_td_ys_bytag = get_wordlevel_ys_by_code(td_tags, wd_train_tags)
    wd_vd_ys_bytag = get_wordlevel_ys_by_code(vd_tags, wd_train_tags)

    tag2word_classifier, td_wd_predictions_by_code, vd_wd_predictions_by_code = {}, {}, {}
    for tag in wd_train_tags:
        td_ys = wd_td_ys_bytag[tag]
        vd_ys = wd_vd_ys_bytag[tag]

        td_joint_feats = zip(td_feats, td_ys)
        vd_joint_feats = zip(vd_feats, vd_ys)


        # MEGAM is many many times faster. IIS takes many minutes
        tagger = maxent.MaxentClassifier.train(td_joint_feats, 'MEGAM', bernoulli=False, trace=0, max_iter= 5)

        # We'll need to store the encoding when retrieving later for stacked model
        tag2word_classifier[tag] = tagger

        td_wd_predictions_by_code[tag] = tagger.classify_many(td_feats)
        vd_wd_predictions_by_code[tag] = tagger.classify_many(vd_feats)

        td_metrics = toDict(compute_metrics(wd_td_ys_bytag,  td_wd_predictions_by_code)[tag])
        vd_metrics = toDict(compute_metrics(wd_vd_ys_bytag,  vd_wd_predictions_by_code)[tag])
        print "Fold:", i, "Tag:", tag
        print processor.__metrics_to_str__(pad_str, tag, td_metrics, vd_metrics)

    merge_dictionaries(wd_td_ys_bytag, cv_wd_td_ys_by_tag)
    merge_dictionaries(wd_vd_ys_bytag, cv_wd_vd_ys_by_tag)
    merge_dictionaries(td_wd_predictions_by_code, cv_wd_td_predictions_by_tag)
    merge_dictionaries(vd_wd_predictions_by_code, cv_wd_vd_predictions_by_tag)
    pass

CB_TAGGING_TD, CB_TAGGING_VD = "CB_TAGGING_TD", "CB_TAGGING_VD"
parameters = dict(config)
#parameters["no_bias"] = True # better with
#parameters["AverageWeights"] = False # Bad - averaging really helps
parameters["extractors"] = map(lambda fn: fn.func_name, extractors)
parameters["min_feat_freq"] = MIN_FEAT_FREQ

wd_algo = "MaxEnt-Binary-NLTK"

wd_td_objectid = processor.persist_results(CB_TAGGING_TD, cv_wd_td_ys_by_tag, cv_wd_td_predictions_by_tag, parameters, wd_algo)
wd_vd_objectid = processor.persist_results(CB_TAGGING_VD, cv_wd_vd_ys_by_tag, cv_wd_vd_predictions_by_tag, parameters, wd_algo)

print processor.results_to_string(wd_td_objectid,   CB_TAGGING_TD,  wd_vd_objectid,     CB_TAGGING_VD,  "TAGGING")

""" WEIGHTED MEAN F1 CONCEPT CODES = 0.727. Better than WINDOW BASED """