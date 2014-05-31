'''
Created on Aug 18, 2013
@author: simon.hughes

Auto-encoder implementation. Can be used to implement a denoising auto-encoder, sparse or contractive auto-encoder
'''

try:
    import gnumpy as np
except:
    print "GNUMPY NOT FOUND, installing numpy"
    import numpy as np

import numpy
from numpy import matlib

class NeuralNetwork(object):
    '''
    classdocs
    '''

    def __init__(self, num_inputs, num_hidden, num_outputs, learning_rate = 0.1, activation_fn = "sigmoid", 
                 initial_wt_max = 0.01, weight_decay = 0.0, desired_sparsity = 0.05, sparsity_wt = 0.00,
                 w1_b1 = None, w2_b2 = None):
        '''
        num_inputs = number of inputs \ outputs
        num_hidden = size of the hidden layer
        activation_fn = activation function to use ("sigmoid" | "tanh")
        initial_wt_max = the initial weights will be set to random weights in the range -initial_wt_max to +initial_wt_max
        weight_decay = a regularization term to stop over-fitting. Only turn on if network converges too fast or overfits the data
        
        w1_b1 are a tuple of weight matrix 1 and bias 1
        w2_b2 are a tuple of weight matrix 2 and bias 2
            This allows weight sharing between networks
        
        '''
        """ Properties """
        self.learning_rate = learning_rate
        self.activation_fn = activation_fn
        self.num_inputs = num_inputs
        self.num_hidden = num_hidden
        self.np_type = type(numpy.array([]))
        """ An auto-encoder """
        self.num_outputs = num_outputs
        self.initial_wt_max = initial_wt_max
        self.weight_decay = weight_decay
        self.desired_sparsity = desired_sparsity
        self.sparsity_wt = sparsity_wt
        """ END Properties """
        
        if w1_b1 == None:
            self.w1 = matlib.rand((num_hidden, num_inputs)) * initial_wt_max
            self.b1 = matlib.rand((1,num_hidden)) * initial_wt_max
        else:
            self.w1 = w1_b1[0]
            self.b1 = w1_b1[1]
        
        assert self.w1.shape == (num_hidden, num_inputs)
        assert self.b1.shape == (1, num_hidden)
        
        if w2_b2 == None:
            self.w2 = matlib.rand((num_outputs, num_hidden)) * initial_wt_max
            self.b2 = matlib.rand((1, num_outputs)) * initial_wt_max
        else:
            self.w2 = w2_b2[0]
            self.b2 = w2_b2[1]
        
        assert self.w2.shape == (num_outputs, num_hidden)
        assert self.b2.shape == (1, num_outputs)

        self.w1 = np.garray(self.w1)
        self.w2 = np.garray(self.w2)
        self.b1 = np.garray(self.b1)
        self.b2 = np.garray(self.b2)

        pass
    
    def train(self, xs, ys, epochs = 100, batch_size = 100):
        if type(xs) != self.np_type:
            inputs = np.garray(xs)
        else:
            inputs = xs
        
        if type(ys) != self.np_type:
            outputs = np.garray(ys)
        else:
            outputs = ys
        
        num_rows = inputs.shape[0]
        
        """ Number of rows in inputs should match outputs """
        assert num_rows == outputs.shape[0]
        
        """ Check outputs match the range for the activation function """
        #self.__validate__(inputs)
        self.__validate__(outputs)
        
        num_batches = num_rows / batch_size
        if num_rows % batch_size > 0:
            num_batches += 1
        
        mse = -1.0
        mae = -1.0
        for epoch in range(epochs):
            if num_batches == 1:
                w1ds, w2ds, b1ds, b2ds, mini_batch_errors = self.__train_mini_batch__(inputs, outputs)
                """ Apply changes """
                self.w1 -= w1ds
                self.w2 -= w2ds
                self.b1 -= b1ds
                self.b2 -= b2ds

                errors = mini_batch_errors.as_numpy_array()
            else:
                errors = None
                for batch in range(num_batches):
                    start = batch * batch_size
                    end = start + batch_size
                    mini_batch_in = inputs[start:end]
                    mini_batch_out = outputs[start:end]
                    if len(mini_batch_in) == 0:
                        continue
                    
                    w1ds, w2ds, b1ds, b2ds, mini_batch_errors = self.__train_mini_batch__(mini_batch_in, mini_batch_out)
                    """ Apply changes """
                    self.w1 -= w1ds
                    self.w2 -= w2ds
                    self.b1 -= b1ds
                    self.b2 -= b2ds

                    if errors == None:
                        errors = mini_batch_errors.as_numpy_array()
                    else:
                        errors = numpy.append(errors, mini_batch_errors.as_numpy_array(), 0 )
            
            mse = numpy.mean(numpy.square(errors) )
            mae = numpy.mean(numpy.abs(errors))
            print "MSE for epoch {0} is {1}".format(epoch, mse),
            print "\tMAE for epoch {0} is {1}".format(epoch, mae)
        return (mse, mae)

    def get_training_errors(self, xs, ys):
        if type(xs) != self.np_type:
            inputs = np.garray(xs)
        else:
            inputs = xs
        
        if type(ys) != self.np_type:
            outputs = np.garray(ys)
        else:
            outputs = ys
        
        num_rows = inputs.shape[0]
        """ Number of rows in inputs should match outputs """
        assert num_rows == outputs.shape[0]
        
        """ Check outputs match the range for the activation function """
        self.__validate__(outputs)
        return self.__train_mini_batch__(inputs, outputs)
     
    def __validate__(self, inputs):
        min_inp = np.min(inputs)
        max_inp = np.max(inputs)
        
        if self.activation_fn == "sigmoid":
            self.__in_range__(min_inp, max_inp,  0.0, 1.0)
        elif self.activation_fn == "tanh":
            self.__in_range__(min_inp, max_inp, -1.0, 1.0)
   
    def __in_range__(self, actual_min, actual_max, exp_min, exp_max):
        assert actual_min >= exp_min
        assert actual_max <= exp_max

    def hidden_activations(self, inputs):
        np_inputs_T = np.garray(inputs).T
        z2 = self.__compute_z__(np_inputs_T, self.w1, self.b1)
        a2 = self.__activate__(z2)
        return a2.T
    
    def prop_up(self, inputs, outputs):
        inputs_T = np.garray(inputs).T
        outputs_T = np.garray(outputs).T
        
        """ Compute activations """
        z2, a2 = self.__prop_up__(inputs_T, self.w1, self.b1)
        z3, a3 = self.__prop_up__(a2, self.w2, self.b2)
        
        """ errors """
        errors = (outputs_T - a3)
        return (a3.T, a2.T, errors.T)

    def feed_forward(self, inputs):
        inputs_T = np.garray(inputs).T

        """ Compute activations """
        z2, a2 = self.__prop_up__(inputs_T, self.w1, self.b1)
        z3, a3 = self.__prop_up__(a2, self.w2, self.b2)

        return a3.T

    def __prop_up__(self, inputs_T, wts, bias):
        
        """ Compute activations """
        z = self.__compute_z__(inputs_T, wts, bias)
        a = self.__activate__(z)
        return (z, a)
                 
    def __train_mini_batch__(self, input_vectors, outputs):
        rows = input_vectors.shape[0]
        inputs_T = input_vectors.T
        outputs_T = outputs.T
        
        """ Compute activations """
        z2, a2 = self.__prop_up__(inputs_T, self.w1, self.b1)
        z3, a3 = self.__prop_up__(a2, self.w2, self.b2)
        
        """ errors = mean( 0.5 sum squared error)  """
        assert outputs_T.shape == a3.shape
        errors = (outputs_T - a3)
         
        deriv3 = self.__derivative__(a3)
        deriv2 = self.__derivative__(a2)
        
        """ Note: multiply does an element wise product, NOT a dot product (Hadambard product)
            inputs_T must have same shape
        """
        #delta3 = np.multiply(-(errors), deriv3) # d3 is - errors multiplied by derivative of activation function
        delta3 = -(errors) * deriv3 # d3 is - errors multiplied by derivative of activation function
        """ THIS IS BACK PROP OF WEIGHTS TO HIDDEN LAYER"""
        
        if self.sparsity_wt > 0.0:
            """ SPARSITY PENALTY """
            pj = np.mean(a2, axis = 1)
            p = self.desired_sparsity
            sparsity_penalty = self.sparsity_wt * ( -p/pj + (1 - p)/(1 - pj) )

            #delta2 = np.multiply( np.dot(self.w2.T, delta3) + sparsity_penalty, deriv2 )
            delta2 = (np.dot(self.w2.T, delta3) + sparsity_penalty) * deriv2
        else:
            #delta2 = np.multiply( np.dot(self.w2.T, delta3), deriv2 )
            delta2 =  np.dot(self.w2.T, delta3) * deriv2

        """ Delta for weights is the dot product of the delta3 (error deltas for output) and activations for that layer"""
        frows = float(rows)
        
        w1delta = np.dot(delta2, inputs_T.T) / frows
        w2delta = np.dot(delta3, a2.T) / frows
        
        """ For each weight in the weight matrix, update it using the input activation * output delta.
            Compute a mean over all examples in the batch. 
            
            The dot product is used here in a very clever  way to compute the activation * the delta 
            for each input and hidden layer node (taking the dot product of each weight over all input_vectors 
            (adding up the weight deltas) and then dividing this by num rows to get the mean
         """
        b1delta = (np.sum(delta2, 1) / frows).T
        b2delta = (np.sum(delta3, 1) / frows).T
        
        if self.weight_decay > 0.0:
            w1ds = self.learning_rate * (w1delta + self.weight_decay * self.w1 )
            w2ds = self.learning_rate * (w2delta + self.weight_decay * self.w2 )
        else:
            w1ds = self.learning_rate * (w1delta )
            w2ds = self.learning_rate * (w2delta )
        
        b1ds = self.learning_rate * b1delta
        b2ds = self.learning_rate * b2delta
        
        """ return a list of errors (one item per row in mini batch) """
        
        """ Compute Mean errors across all training examples in mini batch """
        return (w1ds, w2ds, b1ds, b2ds, errors.T)
   
    def __compute_z__(self, inputs, weights, bias):
        #Can we speed this up by making the bias a column vector?
        return np.dot(weights, inputs) + bias.T
    
    def __activate__(self, z):
        if self.activation_fn == "sigmoid":
            return 1/ (1 + np.exp(-z))
        elif self.activation_fn == "tanh":
            return np.tanh(z)
        else:
            raise NotImplementedError("Only sigmoid and tanh currently implemented")
    
    def __derivative__(self, activations):
        if self.activation_fn == "sigmoid": 
            """ f(z)(1 - f(z)) """
            return activations * (1 - activations)
            #return np.multiply(activations, (1 - activations))
        elif self.activation_fn == "tanh":
            """ 1 - f(z)^2 """
            return 1 - (activations * activations)
            #return 1 - np.square(activations)
        else:
            raise NotImplementedError("Only sigmoid and tanh currently implemented")
        
if __name__ == "__main__":
    
    activation_fn = "sigmoid"
    #activation_fn = "tanh"
    
    """
    xs = [
          [1,    0,     0.5,    0.1],
          [0,    1,     1.0,    0.5],
          [1,    0.5,   1,      0  ],
          [0,    0.9,   0,      1  ],
          [0.25, 0,     0.5,    0.1],
          [0.1,  1,     1.0,    0.5],
          [1,    0.5,   0.65,   0  ],
          [0.7,  0.9,   0,      1  ]
    ]
    """
    xs = [
          [1, 0, 0, 0, 0, 0, 0, 0],
          [0, 1, 0, 0, 0, 0, 0, 0],
          [0, 0, 1, 0, 0, 0, 0, 0],
          [0, 0, 0, 1, 0, 0, 0, 0],
          [0, 0, 0, 0, 1, 0, 0, 0],
          [0, 0, 0, 0, 0, 1, 0, 0],
          [0, 0, 0, 0, 0, 0, 1, 0],
          [0, 0, 0, 0, 0, 0, 0, 1]
          ]
    
    xs = [
          [1, 0, 0, 0, 0, 0, 0, 0],
          [1, 1, 0, 0, 0, 0, 0, 0],
          [0, 0, 1, 1, 0, 0, 0, 0],
          [1, 0, 0, 1, 0, 0, 0, 0],
          [1, 0, 0, 0, 1, 0, 1, 0],
          [0, 0, 0, 0, 0, 1, 0, 0],
          [0, 1, 0, 0, 1, 0, 1, 0],
          [1, 0, 1, 0, 1, 0, 0, 1]
          ]
    if activation_fn == "tanh":
        xs = (xs + 1.0) / 2.0
    
    xs = np.garray(xs)
    ys  = numpy.sum(xs.as_numpy_array(), axis=1, keepdims = True) * 1.0
    ys = (ys - np.min(ys)) / (np.max(ys) - np.min(ys))
    ys = np.garray(ys)
    """ Test as an Auto Encoder """
    ys = xs
    
    num_inputs = len(xs[0])
    num_hidden = int(round(np.log2(num_inputs)))

    """ Note that the range of inputs for tanh is 2* sigmoid, and so the MAE should be 2* """
    ae = NeuralNetwork(num_inputs, num_hidden, len(ys[0]),  learning_rate = 0.1,
                        activation_fn = activation_fn,
                        weight_decay=0.0, desired_sparsity=0.05, sparsity_wt=0.0)
    
    ae.train(xs, ys, 10000, batch_size = 4)
   
    xs_T = np.garray(xs).T
    activations = ae.__activate__(xs_T)
    
    print ""
    print ae.w1
    print ae.w2
    print ""
    print ae.hidden_activations(xs)
    print numpy.round(ae.hidden_activations(xs).as_numpy_array())
    print ""
    print ys
    print ae.prop_up(xs, xs)[0]
    print numpy.round(ae.prop_up(xs, xs)[0].as_numpy_array())
    pass

    xs = [
        [1, 0, 0, 0, 0, 0, 0, 0],
        [1, 1, 0, 0, 0, 0, 0, 0],
        [0, 0, 1, 1, 0, 0, 0, 0],
        [1, 0, 0, 1, 0, 0, 0, 0],
        [1, 0, 0, 0, 1, 0, 1, 0],
        [0, 0, 0, 0, 0, 1, 0, 0],
        [0, 1, 0, 0, 1, 0, 1, 0],
        [1, 0, 1, 0, 1, 0, 0, 1]
    ]
    xs = np.garray(xs)
    ys = numpy.sum(xs.as_numpy_array(), axis=1, keepdims=True) * 1.0
    ys = (ys - np.min(ys)) / (np.max(ys) - np.min(ys))
    ys = np.garray(ys)

    num_inputs = len(xs[0])
    num_hidden = int(round(np.log2(num_inputs)))

    nn = NeuralNetwork(num_inputs, num_hidden, len(ys[0]))
    nn.train(xs, ys)
