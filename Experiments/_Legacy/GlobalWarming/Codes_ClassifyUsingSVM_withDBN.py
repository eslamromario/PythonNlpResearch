from sklearn import svm
from GwExperimentBase import *
import dbn

class Codes_ClassifyUsingSVM_withDBN(GwExperimentBase):
    sharedDbn = None

    def __init__(self, kernel, c):
        self.kernel = kernel
        self.c = c
        self.dbn = Codes_ClassifyUsingSVM_withDBN.sharedDbn
        
    def get_vector_space(self, tokenized_docs):
        return self.term_freq_vspace(tokenized_docs)
    
    def create_classifier(self, code):
        def svm_create(xs, ys):
            
            if self.dbn == None:
                layers = [xs.shape[1], 600, 600]
                epochs = [2000, 2000]
                learning_rate = [0.5, 0.5]
                
                net = dbn.DBN(layers, learning_rate)
                net.train(xs, epochs)
                
                # Store for other instances
                Codes_ClassifyUsingSVM_withDBN.sharedDbn = net
                self.dbn = net
            
            if self.kernel == 'linear':
                svm_cls = svm.LinearSVC(C = self.c, dual = True)
            else:
                svm_cls = svm.SVC(kernel = self.kernel, C = self.c)
                
            data = self.dbn.get_activations(xs,3)
            svm_cls.fit(data, ys)
            return svm_cls
        return svm_create
        
    def classify(self):
        def classify(classifier, vd):
            data = self.dbn.get_activations(vd,3)
            return classifier.predict(data) 
        return classify

    def get_training_data(self, distance_matrix, id2word):
        return self.get_sparse_matrix_data(distance_matrix, id2word)
    
    def label_mapper(self):
        return Converter.get_svm_val

    def matrix_value_mapper(self):
        #return None
        return Converter.to_binary

if __name__ == "__main__":
    kernel = 'linear'
    C = 5.0
    
    #cl = Codes_ClassifyUsingSVM(kernel, float(C))
    #(mean_metrics, wt_mean_metrics) = cl.Run("Codes_ClassfyUsingSVM_kernel_{0}_c_{1}.txt".format(kernel, str(C)))
    
    bestC = 1.0
    best_f1 = 0   
     
    for C in range(5, 6):
        cl = Codes_ClassifyUsingSVM_withDBN(kernel, float(C))
        (mean_metrics, wt_mean_metrics) = cl.Run("Codes_ClassifyUsingSVM_withDBN_kernel_{0}_c_{1}.txt".format(kernel, str(C)))
        f1_score = wt_mean_metrics.f1_score
        if f1_score > best_f1:
            best_f1 = f1_score
            bestC = C
            print "Best C Value: {0} with F1: {1}".format(str(bestC), best_f1)
    
    print "Best C Value: {0} with F1: {1}".format(str(bestC), best_f1)
    