# Importing necessary libraries

import tensorflow as tf
import numpy as np
from tensorflow.python.keras.models import Model
from tensorflow.python.keras.layers import Input,Dense,GRU,CuDNNGRU,Embedding
from tensorflow.keras.optimizers import RMSprop
from tensorflow.python.keras.callbacks import ModelCheckpoint
from tensorflow.python.keras.preprocessing.text import Tokenizer
from tensorflow.python.keras.preprocessing.sequence import pad_sequences

from google.colab import drive
drive.mount("/content/drive")

tf.compat.v1.disable_eager_execution()

# Reading data 
# Start mark and end mark are for decoder
start_mark = "ssss "
end_mark = " eeee"

# source will be English and destination will be Turkish
data_src = []
data_dest = []

for line in open("/content/drive/MyDrive/tur.txt",encoding="utf-8"):

  src_text,dest_text = line.rstrip().split("\t")

  dest_text = start_mark + dest_text + end_mark

  data_src.append(src_text)
  data_dest.append(dest_text)

print(data_src[100])
print(data_dest[100])

len(data_src)

# in order to add some new stuff (such as padding options,reversing) to Tokenizer, I'll write a wrap

class TokenizerWrap(Tokenizer):

  def __init__(self,texts,padding,reverse=False,num_words=None):
    """
    Parameters:
    texts = texts that we create word vocab and sequences
    padding = padding type: pre or post
    reverse = whether reverse the text or not, if reverse truncating is pre else truncating is post
    num_words = if you wanna make your model smaller, specify num words.
    """

    Tokenizer.__init__(self,num_words=num_words)
    self.fit_on_texts(texts)
    self.index2word = dict(zip(self.word_index.values(),self.word_index.keys()))
    self.tokens = self.texts_to_sequences(texts)

    if reverse:
      # Because in NMT starts of sentences are more valuable than the ends.
      truncating = "pre"
      self.tokens = [list(reversed(pc)) for pc in self.tokens]
    else:
      truncating = "post"
    
    self.num_tokens = [len(seq) for seq in self.tokens]
    # This value will be higher than %95 of the lengths of the data
    self.max_tokens = np.mean(self.num_tokens) + 2 * np.std(self.num_tokens)
    self.max_tokens = int(self.max_tokens)

    self.tokens_padded = pad_sequences(self.tokens,
                                      maxlen=self.max_tokens,
                                      padding=padding,
                                      truncating=truncating
                                      )
  

  def token_to_word(self,token):
    word = " " if token == 0 else self.index2word[token]
    return word
  
  def tokens_to_string(self,tokens):
    words = [self.index2word[token] for token in tokens if token != 0 ]
    return " ".join(words)

  def text_to_tokens(self,text,padding,reverse=False):

    tokens = np.array(self.texts_to_sequences([text]))


    if reverse:
      truncating = "pre"
      tokens = np.flip(tokens,axis=1)

    else:
      truncating = "post"
    
    pad_tokens = pad_sequences(tokens,
                               maxlen=self.max_tokens,
                               padding=padding,
                               truncating=truncating
                               )
    
    return pad_tokens

# We use pre padding reversing and pre truncating because when we're creating our 
# thought vector using encoder adding zeros to start is better because
# model will evaluate real words lastly and create a better thought vector
tokenizer_src = TokenizerWrap(texts=data_src,
                              padding="pre",
                              reverse=True,
                              num_words=None
                              )

tokenizer_dest = TokenizerWrap(texts=data_dest,
                               padding="post",
                               reverse=False,
                               num_words=None
                               )

tokens_src = tokenizer_src.tokens_padded
tokens_dest = tokenizer_dest.tokens_padded
print(tokens_src.shape)
print(tokens_dest.shape)

tokenizer_dest.tokens_to_string(tokens_dest[200000])

tokens_src[200000]

tokens_dest[200000]

# Input and Output Datas
# When we're talking about encoder, input is same with source tokens
# When we're talking about decoder input is the tokens with start mark and output is the tokens without start mark

encoder_input_data = tokens_src
decoder_input_data = tokens_dest[:,:-1] 
decoder_output_data = tokens_dest[:,1:]

print(decoder_input_data[200000])
print(decoder_output_data[200000])

# We'll also use these numbers when we're building Embedding layers of encoder and decoder.
num_encoder_words = len(tokenizer_src.word_index)
num_decoder_words = len(tokenizer_dest.word_index)

print("English vocab length:",num_encoder_words)
print("Turkish vocab length:",num_decoder_words)

# In encoder embedding layer we'll use pretrained glove vectors because training embeddings with small data
# is meanless if it's not a necessary.

word2vec = {}
with open("/content/drive/MyDrive/glove.6B.100d.txt",encoding="UTF-8") as F:
  for line in F:
    vals = line.split()
    word = vals[0]
    vector = np.asarray(vals[1:])
    word2vec[word] = vector
  
# These vector file includes 400K unique words so we'll probably find all words that we have in our vocab.

# uniform embedding matrix 
VEC_SIZE = 100
embedding_matrix = np.random.uniform(-1,1,[num_encoder_words,VEC_SIZE])

# Changing random values with pre trained vectors.
for word,index in tokenizer_src.word_index.items():
  if index < num_encoder_words:
    vec = word2vec.get(word)
    if vec is not None:
      embedding_matrix[index] = vec

embedding_matrix.shape

# Encoder layers
encoder_input = Input(shape=(None,),name="encoder_input")
encoder_embedding = Embedding(input_dim=num_encoder_words,
                              output_dim=VEC_SIZE,
                              weights=[embedding_matrix],
                              trainable=True,
                              name="encoder_embedding"
                              )
STATE_SIZE = 256

encoder_gru1 = CuDNNGRU(STATE_SIZE,name="encoder_gru1",return_sequences=True)
encoder_gru2 = CuDNNGRU(STATE_SIZE,name="encoder_gru2",return_sequences=True)
encoder_gru3 = CuDNNGRU(STATE_SIZE,name="encoder_gru3",return_sequences=False)

def connectEncoder():
  net = encoder_input
  net = encoder_embedding(net)
  net = encoder_gru1(net)
  net = encoder_gru2(net)
  net = encoder_gru3(net)
  return net

encoder_output = connectEncoder()

# decoder layers
# we'll connect thought vector here
decoder_initial_state = Input(shape=(STATE_SIZE,),name="decoder_initial_state")
decoder_input = Input(shape=(None,),name="decoder_input")
decoder_embedding = Embedding(input_dim=num_decoder_words,
                              output_dim=VEC_SIZE,
                              name="decoder_embedding"
                              )

decoder_gru1 = CuDNNGRU(STATE_SIZE,name="decoder_gru1",return_sequences=True)
decoder_gru2 = CuDNNGRU(STATE_SIZE,name="decoder_gru2",return_sequences=True)
decoder_gru3 = CuDNNGRU(STATE_SIZE,name="decoder_gru3",return_sequences=True)
decoder_dense = Dense(num_decoder_words,activation="linear",name="decoder_dense")

# connecting layers of decoder
def connectDecoder(initial_state):
  net = decoder_input
  net = decoder_embedding(net)
  net = decoder_gru1(net,initial_state=initial_state)
  net = decoder_gru2(net,initial_state=initial_state)
  net = decoder_gru3(net,initial_state=initial_state)
  net = decoder_dense(net)

  return net

decoder_output = connectDecoder(encoder_output)

# We'll create three models, train model, test encoder and test decoder
model_train = Model(inputs=[encoder_input,decoder_input],outputs=[decoder_output])
model_encoder = Model(inputs=[encoder_input],outputs=[encoder_output])

# In order to make a independent decoder let's change the initial state with our placeholder
decoder_output = connectDecoder(decoder_initial_state)
model_decoder = Model(inputs=[decoder_input,decoder_initial_state],outputs=[decoder_output])

# we'll use sparse categorical cross entropy because we can't fit a 94k x 94k one hot matrix to our ram

def sparse_categorical_crossentropy(y_true,y_preds):
  loss = tf.nn.sparse_softmax_cross_entropy_with_logits(labels=y_true,logits=y_preds)
  loss_mean = tf.reduce_mean(loss)
  return loss_mean

optimizer = RMSprop(lr=1e-3)

from tensorflow.compat.v1 import placeholder


decoder_target = placeholder(dtype="int32",shape=[None,None])
model_train.compile(optimizer=optimizer,
                    loss=sparse_categorical_crossentropy,
                    target_tensors=[decoder_target]
                    )

path_checkpoint = "checkpoint.keras"
checkpoint = ModelCheckpoint(filepath=path_checkpoint,save_weights_only=True)

try:
  model_train.load_weights(path_checkpoint)
  print("Weigths loaded succesfully")
except Exception as E:
  print("There is no checkpoint or it is not enable to use, training will start from scratch")
  print("\n\n")
  print(E)

x_data = {"encoder_input":encoder_input_data,"decoder_input":decoder_input_data}
y_data = {"decoder_dense":decoder_output_data}

model_train.fit(x=x_data,
                y=y_data,
                batch_size=128,
                epochs=15,
                callbacks=[checkpoint])

token_start = 1
token_end = 2

def translate(input_text,true_output_text=None):
  input_tokens = tokenizer_src.text_to_tokens(text=input_text,
                                              reverse=True,
                                              padding="pre"
                                              )
  initial_state = model_encoder.predict(input_tokens)
  max_tokens = tokenizer_dest.max_tokens

  decoder_input_data = np.zeros(shape=(1,max_tokens),dtype=np.int)
  token_int = token_start
  output_text = " "
  count_tokens = 0
  

  while token_int != token_end and count_tokens < max_tokens:
    decoder_input_data[0,count_tokens] = token_int
    x_data = {"decoder_initial_state":initial_state,"decoder_input":decoder_input_data}

    decoder_output = model_decoder.predict(x_data)
    token_onehot = decoder_output[0,count_tokens,:]
    token_int = np.argmax(token_onehot)
    sampled_word = tokenizer_dest.token_to_word(token_int)
    output_text = output_text + " " + sampled_word
    count_tokens += 1

  print("Input Text: (English)")
  print(input_text)
  print()
  print("Output Text: (Turkish)")
  print(output_text.strip())

translate("")

model_encoder.save("encoder.keras")
model_decoder.save("decoder.keras")
