# coding: utf-8
import datetime
import logging
from collections import defaultdict
from typing import Any, List, Set, Tuple

import dill
import numpy as np
import pymongo
from joblib import Parallel, delayed
from sklearn.linear_model import LogisticRegression

from CrossValidation import cross_validation
from Settings import Settings
from crel_helper import get_cr_tags
from function_helpers import get_function_names, get_functions_by_name
from load_data import load_process_essays
from results_procesor import ResultsProcessor, __MICRO_F1__
from searn_parser import SearnModelTemplateFeatures
from window_based_tagger_config import get_config
from wordtagginghelper import merge_dictionaries
from cost_functions import *
from template_feature_extractor import *

# Logging
logging.basicConfig(format='%(asctime)s : %(levelname)s : %(message)s', level=logging.INFO)
logger = logging.getLogger()

# Data Set Partition
CV_FOLDS = 5
MIN_FEAT_FREQ = 5

# Global settings

settings = Settings()
root_folder = settings.data_directory + "CoralBleaching/Thesis_Dataset/"
training_folder = root_folder + "Training" + "/"
test_folder = root_folder + "Test" + "/"
training_pickled = settings.data_directory + "CoralBleaching/Thesis_Dataset/training.pl"
# NOTE: These predictions are generated from the "./notebooks/SEARN/Keras - Train Tagger and Save CV Predictions For Word Tags.ipynb" notebook
# used as inputs to parsing model
rnn_predictions_folder = root_folder + "Predictions/Bi-LSTM-4-SEARN/"

config = get_config(training_folder)

# Get Test Data In Order to Get Test CRELS
# load the test essays to make sure we compute metrics over the test CR labels
test_config = get_config(test_folder)
tagged_essays_test = load_process_essays(**test_config)
########################################################

fname = rnn_predictions_folder + "essays_train_bi_directional-True_hidden_size-256_merge_mode-sum_num_rnns-2_use_pretrained_embedding-True.dill"
with open(fname, "rb") as f:
    pred_tagged_essays = dill.load(f)

logger.info("Started at: " + str(datetime.datetime.now()))
logger.info("Number of pred tagged essays %i" % len(pred_tagged_essays))  # should be 902

cr_tags = get_cr_tags(train_tagged_essays=pred_tagged_essays, tag_essays_test=tagged_essays_test)
cv_folds = cross_validation(pred_tagged_essays, CV_FOLDS)  # type: List[Tuple[Any,Any]]

def evaluate_model(
        collection_prefix: str,
        folds: List[Tuple[Any, Any]],
        extractor_fn_names_lst: List[str],
        cost_function_name: str,
        beta: float,
        ngrams: int,
        stemmed: bool,
        max_epochs: int,
        down_sample_rate=1.0) -> float:

    if down_sample_rate < 1.0:
        new_folds = []  # type: List[Tuple[Any, Any]]
        for i, (essays_TD, essays_VD) in enumerate(folds):
            essays_TD = essays_TD[:int(down_sample_rate * len(essays_TD))]
            essays_VD = essays_VD[:int(down_sample_rate * len(essays_VD))]
            new_folds.append((essays_TD, essays_VD))
        folds = new_folds  # type: List[Tuple[Any, Any]]

    #logger.info("\tModei={model}".format(model=str(BASE_LEARNER_FACT())))

    parallel_results = Parallel(n_jobs=len(folds))(
        delayed(model_train_predict)(essays_TD, essays_VD, extractor_fn_names_lst, cost_function_name, ngrams, stemmed,
                                     beta, max_epochs)
        for essays_TD, essays_VD in folds)

    # parallel_results = [model_train_predict(essays_TD, essays_VD, extractor_fn_names_lst, cost_function_name, ngrams, stemmed,
    #                                  beta, max_epochs)
    #     for essays_TD, essays_VD in folds]

    # cv_sent_td_ys_by_tag, cv_sent_td_predictions_by_tag = defaultdict(list), defaultdict(list)
    # cv_sent_vd_ys_by_tag, cv_sent_vd_predictions_by_tag = defaultdict(list), defaultdict(list)
    #
    # # record the number of features in each fold
    # number_of_feats = []

    sent_vd_predictions_by_tag_by_fold = {}
    sent_vd_ys_by_tag_by_code = {}

    # Parallel is almost 5X faster!!!
    for fold_ix, \
        (num_feats,
         sent_td_ys_bycode, sent_vd_ys_bycode,
         sent_td_pred_ys_bycode, sent_vd_pred_ys_bycode) in enumerate(parallel_results):

        # number_of_feats.append(num_feats)

        # merge_dictionaries(sent_td_ys_bycode, cv_sent_td_ys_by_tag)
        # merge_dictionaries(sent_vd_ys_bycode, cv_sent_vd_ys_by_tag)
        # merge_dictionaries(sent_td_pred_ys_bycode, cv_sent_td_predictions_by_tag)
        # merge_dictionaries(sent_vd_pred_ys_bycode, cv_sent_vd_predictions_by_tag)

        sent_vd_ys_by_tag_by_code[fold_ix] = sent_vd_ys_bycode
        sent_vd_predictions_by_tag_by_fold[fold_ix] = sent_vd_pred_ys_bycode
        # break

    # Mongo settings recording
    return sent_vd_predictions_by_tag_by_fold, sent_vd_ys_by_tag_by_code

def model_train_predict(essays_TD, essays_VD, extractor_names, cost_function_name, ngrams, stemmed, beta, max_epochs):

    #logger.info("\tModei={model}".format(model=str(BASE_LEARNER_FACT())))

    extractors = get_functions_by_name(extractor_names, all_extractor_fns)
    # get single cost function
    cost_fn = get_functions_by_name([cost_function_name], all_cost_functions)[0]
    assert cost_fn is not None, "Cost function look up failed"
    # Ensure all extractors located
    assert len(extractors) == len(extractor_names), "number of extractor functions does not match the number of names"

    template_feature_extractor = NonLocalTemplateFeatureExtractor(extractors=extractors)
    if stemmed:
        ngram_extractor = NgramExtractorStemmed(max_ngram_len=ngrams)
    else:
        ngram_extractor = NgramExtractor(max_ngram_len=ngrams)
    parse_model = SearnModelTemplateFeatures(feature_extractor=template_feature_extractor,
                                             cost_function=cost_fn,
                                             min_feature_freq=MIN_FEAT_FREQ,
                                             ngram_extractor=ngram_extractor, cr_tags=cr_tags,
                                             base_learner_fact=BASE_LEARNER_FACT,
                                             beta=beta,
                                             # log_fn=lambda s: print(s))
                                             log_fn=lambda s: None)

    parse_model.train(essays_TD, max_epochs=max_epochs)

    num_feats = template_feature_extractor.num_features()

    sent_td_ys_bycode = parse_model.get_label_data(essays_TD)
    sent_vd_ys_bycode = parse_model.get_label_data(essays_VD)

    sent_td_pred_ys_bycode = parse_model.predict(essays_TD)
    sent_vd_pred_ys_bycode = parse_model.predict(essays_VD)

    return num_feats, sent_td_ys_bycode, sent_vd_ys_bycode, sent_td_pred_ys_bycode, sent_vd_pred_ys_bycode


def get_training_data_word_labels(tessays):
    # outputs

    ys_bytag = defaultdict(list)
    seq_lens = []

    # cut texts after this number of words (among top max_features most common words)
    for essay in tessays:
        for sentence in essay.sentences:
            row = []
            y_found = False
            y_seq = []
            unique_tags = set()

            for word, tags in sentence:

                row.append(id)
                # remove unwanted tags
                tags = set(cr_tags).intersection(tags)
                unique_tags.update(tags)
                # retain all tags for evaluation (not just most common)

                for t in cr_tags:
                    if t in tags:
                        ys_bytag[t].append(1)
                    else:
                        ys_bytag[t].append(0)

            seq_lens.append(len(sentence))
    assert len(ys_bytag[list(ys_bytag.keys())[0]]) == sum(seq_lens)
    return ys_bytag, seq_lens

def get_overlapping_codes(seq_lens, ys_by_tag):

    offset = 0
    sentix2overlapping_codes = defaultdict(set)
    sentix2NONEoverlapping_codes = defaultdict(set)

    for i in range(len(seq_lens)):
        len_of_sequence = seq_lens[i]
        end_offset = offset + len_of_sequence
        ysbytag4seq = {}
        for tag in cr_tags:
            all_ys = ys_by_tag[tag]
            ys = all_ys[offset: end_offset]
            assert len(ys) == len_of_sequence, "[{i}] {a} : {b} : {c} tag={tag}".format(
                i=i, a=len(ys), b=len_of_sequence, c=len(all_ys), tag=tag)
            # any labels?
            if sum(ys) > 0:
                ysbytag4seq[tag] = ys

        if len(ysbytag4seq) > 0:
            if len(ysbytag4seq) > 1:
                for posn in range(len_of_sequence):
                    overlapping_tags = set()
                    for t in ysbytag4seq.keys():
                        yval = ysbytag4seq[t][posn]
                        if yval == 1:
                            overlapping_tags.add(t)
                    if len(overlapping_tags) > 1:
                        sentix2overlapping_codes[i].update(overlapping_tags)
            # get all overlapping tags for sentence
            all_overlapping_tags = sentix2overlapping_codes[i]
            for tag in ysbytag4seq.keys():  # for all sentence tags
                if tag not in all_overlapping_tags:
                    sentix2NONEoverlapping_codes[i].add(tag)
        offset = end_offset
    return sentix2overlapping_codes, sentix2NONEoverlapping_codes

def compute_preds(pred_test_predictions_by_tag_sent, sentix2overlapping_codes):
    preds = []
    for six, tags in sentix2overlapping_codes.items():
        for t in tags:
            lbls = pred_test_predictions_by_tag_sent[t]
            preds.append(lbls[six])
    return preds

fold2_ys_word  = {}
fold2_seq_lens = {}

for fold_ix, (essays_TD, essays_VD) in enumerate(cv_folds):
    # Test Data
    fold2_ys_word[fold_ix], fold2_seq_lens[fold_ix] = get_training_data_word_labels(essays_VD)

LINE_WIDTH = 80

# other settings
DOWN_SAMPLE_RATE = 1.0  # For faster smoke testing the algorithm
BASE_LEARNER_FACT = None
COLLECTION_PREFIX = "CR_CB_SHIFT_REDUCE_PARSER_TEMPLATED_HYPER_PARAM"

# some of the other extractors aren't functional if the system isn't able to do a basic parse
# so the base extractors are the MVP for getting to a basic parser, then additional 'meta' parse
# features from all_extractors can be included
base_extractors = [
    single_words,
    word_pairs,
    three_words,
    between_word_features
]

all_extractor_fns = base_extractors + [
    word_distance,
    valency,
    unigrams,
    third_order,
    label_set,
    size_features
]

all_cost_functions = [
    micro_f1_cost,
    micro_f1_cost_squared,
    micro_f1_cost_plusone,
    micro_f1_cost_plusepsilon,
    binary_cost,
    inverse_micro_f1_cost,
    uniform_cost
]

all_extractor_fn_names = get_function_names(all_extractor_fns)
base_extractor_fn_names = get_function_names(base_extractors)
all_cost_fn_names = get_function_names(all_cost_functions)

for ngrams in [1]:

    logger.info("*" * LINE_WIDTH)
    logger.info("NGRAM SIZE: {ngram}".format(ngram=ngrams))

    for stemmed in [True]:

        logger.info("*" * LINE_WIDTH)
        logger.info("Stemmed: {stemmed}".format(stemmed=stemmed))

        # update top level stem setting too
        config["stem"] = stemmed

        for cost_function_name in [micro_f1_cost_plusepsilon.__name__]:

            logger.info("*" * LINE_WIDTH)
            logger.info("COST FN: {cost_fn}".format(cost_fn=cost_function_name))

            #current_extractor_names = []  # type: List[str]
            # best
            best_extractor_names = ['single_words', 'between_word_features', 'label_set',
                                    'three_words', 'third_order', 'unigrams'] # type: List[str]

            best_f1 = -1.0
            logger.info("-" * LINE_WIDTH)

            for dual in [True]:
                # for fit_intercept in [True, False]: # remove as non-optimal and to speed up
                for fit_intercept in [True]:
                    for penalty in ["l2"]:
                        # dual only support l2
                        if dual and penalty != "l2":
                            continue

                        for beta in [0.5]:
                            for max_epochs in [2]:

                                for C in [0.5]:

                                    BASE_LEARNER_FACT = lambda : LogisticRegression(
                                       dual=dual,
                                       C=C,
                                       penalty=penalty,
                                       fit_intercept=fit_intercept)

                                    logger.info("\tEvaluating parameters: beta={beta} max_epochs={max_epochs} dual={dual}, C={C}, penalty={penalty}, fit_intercept={fit_intercept}".format(
                                        dual=dual,
                                        C=C,
                                        penalty=penalty,
                                        fit_intercept=fit_intercept,
                                        beta=beta,
                                        max_epochs=max_epochs
                                    ))
                                    logger.info(
                                        "\tExtractors: {extractors}".format(extractors=",".join(best_extractor_names)))

                                    # RUN hyper parameter evalution
                                    sent_preds_by_code, sent_ys_by_code = evaluate_model(
                                        collection_prefix=COLLECTION_PREFIX,
                                        folds=cv_folds,
                                        extractor_fn_names_lst=best_extractor_names,
                                        cost_function_name=cost_function_name,
                                        ngrams=ngrams,
                                        beta=beta,
                                        stemmed=stemmed,
                                        down_sample_rate=DOWN_SAMPLE_RATE,
                                        max_epochs=max_epochs)


                                    preds_for_overlap = []
                                    preds_for_NONE_overlap = []

                                    for fold_ix in range(CV_FOLDS):

                                        ys_by_tag = fold2_ys_word[fold_ix]
                                        seq_len_test = fold2_seq_lens[fold_ix]

                                        sentix2overlapping_codes, sentix2NONEoverlapping_codes = \
                                            get_overlapping_codes(seq_len_test, ys_by_tag)

                                        pred_test_predictions_by_tag_sent = sent_preds_by_code[fold_ix]

                                        overlap_preds = compute_preds(pred_test_predictions_by_tag_sent, sentix2overlapping_codes)
                                        none_overlap_preds = compute_preds(pred_test_predictions_by_tag_sent, sentix2NONEoverlapping_codes)

                                        preds_for_overlap.extend(overlap_preds)
                                        preds_for_NONE_overlap.extend(none_overlap_preds)

                                    avg_overlap_preds, avg_none_overlap_preds = np.mean(preds_for_overlap), np.mean(preds_for_NONE_overlap)
                                    # Note this is recall NOT precision - we are filtering by the labels (recall) not by the predictions (precision)
                                    print("Micro-recall, overlap: {overlap} without: {without}".format(
                                        overlap=avg_overlap_preds, without=avg_none_overlap_preds))



# Micro-precision, overlap: 0.6792777300085985 without: 0.7525773195876289


