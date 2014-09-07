import os
import Settings
import re, collections
from collections import defaultdict

class SpellingCorrector(object):

    """ 
        This is a simple spelling corrector taking from Peter Norvig's site
    """    
    def __init__(self, words = None):

        #settings = Settings.Settings()
        dir = "/Users/simon.hughes/GitHub/NlpResearch/PythonNlpResearch/Data/PublicDataSets/"
        dictionary_file = dir + "words.lst"

        if not words:
            large_text_file = dir + "big.txt"
            words = self.extract_words(file(large_text_file).read())

        word_freq = self.train(words)

        with open(dictionary_file, "r+") as f:
            words_in_dict = f.readlines()

        self.nwords = defaultdict(int)
        for line in words_in_dict:
            word = line.lower().strip()
            self.nwords[word] += 1
            if word in word_freq:
                self.nwords[word] += word_freq[word]

        #add apostrophe
        self.alphabet = "abcdefghijklmnopqrstuvwxyz'"
        self.memoize = {}
    
    def extract_words(self, text):
        return re.findall('[a-z]+', text.lower()) 

    def train(self,features):
        model = collections.defaultdict(lambda: 1)
        for f in features:
            model[f] += 1
        return model

    def edits1(self, word):
        splits     = [(word[:i], word[i:]) for i in range(len(word) + 1)]
        deletes    = [a + b[1:] for a, b in splits if b]
        transposes = [a + b[1] + b[0] + b[2:] for a, b in splits if len(b)>1]
        replaces   = [a + c + b[1:] for a, b in splits for c in self.alphabet if b]
        inserts    = [a + c + b     for a, b in splits for c in self.alphabet]
        return set(deletes + transposes + replaces + inserts)
    
    def known_edits2(self, word):
        return set(e2 for e1 in self.edits1(word) for e2 in self.edits1(e1) if e2 in self.nwords)
    
    def known(self, words): return set(w for w in words if w in self.nwords)
    
    def correct(self, word):
        #don't correct words with numerics
        #need to ignore ' here
        if not word.replace("'","").isalpha():
            return word
        if word in self.memoize:
            return self.memoize[word]
        correction = self.__correct__(word)
        self.memoize[word] = correction
        return correction

    def __correct__(self, word):
        candidates = self.known([word]) or self.known(self.edits1(word)) or self.known_edits2(word) or [word]
        return max(candidates, key=self.nwords.get)

if __name__ == "__main__":
    sc = SpellingCorrector()
    
    print "appe", sc.correct("appe")
    print "apple", sc.correct("apple")
    print "aple", sc.correct("aple")
    print "appl", sc.correct("appl")
    print "appple", sc.correct("appple")
    