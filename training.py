"""
training.py

This module contains the training pipeline for the image captioning model.

It includes:
- Importing necessary modules and settings.
- Defining a callback for logging training metrics with Weights & Biases (wandb).
- Reading the API key for wandb from a file and logging in.
- The main training script will be further down in the file (not shown in the excerpt).

The module uses TensorFlow for model training, and Weights & Biases for logging training metrics.

The settings for the model and the dataset are imported from the settings and dataset modules respectively. The model components are imported from the model module.
"""

from dataset import make_dataset, custom_standardization, reduce_dataset_dim, valid_test_split
from settings import *
from custom_schedule import custom_schedule
from model import get_cnn_model, TransformerEncoderBlock, TransformerDecoderBlock, ImageCaptioningModel
from utility import save_tokenizer
import json
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras.layers import TextVectorization
import numpy as np
import wandb
from keras.callbacks import LambdaCallback
from datetime import datetime
from tensorflow.python.profiler import profiler_v2
from tensorflow.python.keras.callbacks import TensorBoard
# tf.config.run_functions_eagerly(True)
# Define the callback

# Set the policy
# tf.keras.mixed_precision.set_global_policy('mixed_float16')


wandb_callback = LambdaCallback(
    on_batch_end=lambda batch, logs: wandb.log({
        'batch_train_loss': logs['loss'],
        'batch_train_accuracy': logs['acc']
    }),
    on_epoch_end=lambda epoch, logs: wandb.log({
        'epoch_train_loss': logs['loss'],
        # 'epoch_train_accuracy': logs['acc'],
        'epoch_valid_loss': logs.get('val_loss', None),
        'epoch_valid_accuracy': logs.get('val_acc', None)
    })
)


# Read the API key from the file
with open('apikey.txt', 'r') as file:
    api_key = file.read().strip()

# Login to wandb
wandb.login(key=api_key)

# Start a new run
run = wandb.init(project='image-labeling-project', entity='dulcich')


print('tensorflow version: ', tf.__version__)
print("Num GPUs Available: ", len(tf.config.list_physical_devices('GPU')))

# Load dataset
with open(train_data_json_path) as json_file:
    train_data = json.load(json_file)
with open(valid_data_json_path) as json_file:
    valid_data = json.load(json_file)
with open(text_data_json_path) as json_file:
    text_data = json.load(json_file)

# For reduce number of images in the dataset
if REDUCE_DATASET:
    train_data, valid_data = reduce_dataset_dim(train_data, valid_data)
print("Number of training samples: ", len(train_data))
print("Number of validation samples: ", len(valid_data))

# Log the number of training and validation samples
wandb.log({'Number of training samples': len(train_data), 'Number of validation samples': len(valid_data)})

# Define tokenizer of Text Dataset
tokenizer = TextVectorization(
    max_tokens=MAX_VOCAB_SIZE,
    output_mode="int",
    output_sequence_length=SEQ_LENGTH,
    standardize=custom_standardization,
    ngrams=1
)

# Adapt tokenizer to Text Dataset
tokenizer.adapt(text_data)

# Define vocabulary size of Dataset
VOCAB_SIZE = len(tokenizer.get_vocabulary())
#print(VOCAB_SIZE)

# 20k images for validation set and 13432 images for test set
valid_data, test_data  = valid_test_split(valid_data)
print("Number of validation samples after splitting with test set: ", len(valid_data))
print("Number of test samples: ", len(test_data))

# Setting batch dataset
train_dataset = make_dataset(list(train_data.keys()), list(train_data.values()), data_aug=TRAIN_SET_AUG, tokenizer=tokenizer)
valid_dataset = make_dataset(list(valid_data.keys()), list(valid_data.values()), data_aug=VALID_SET_AUG, tokenizer=tokenizer)
if TEST_SET:
    test_dataset = make_dataset(list(test_data.keys()), list(test_data.values()), data_aug=False, tokenizer=tokenizer)

# Define Model
cnn_model = get_cnn_model()

encoder = TransformerEncoderBlock(
    embed_dim=EMBED_DIM, dense_dim=FF_DIM, num_heads=NUM_HEADS
)
encoder2 = TransformerEncoderBlock(
    embed_dim=EMBED_DIM, dense_dim=FF_DIM, num_heads=NUM_HEADS
)
decoder = TransformerDecoderBlock(
    embed_dim=EMBED_DIM, ff_dim=FF_DIM, num_heads=NUM_HEADS, vocab_size=VOCAB_SIZE
)
caption_model = ImageCaptioningModel(
    cnn_model=cnn_model, encoder=encoder, encoder2=encoder2, decoder=decoder #, tokenizer=tokenizer
)

# Define the loss function
cross_entropy = keras.losses.SparseCategoricalCrossentropy(from_logits=True, reduction="none")

# EarlyStopping criteria
early_stopping = keras.callbacks.EarlyStopping(patience=3, restore_best_weights=True)

# Create a learning rate schedule
lr_scheduler = custom_schedule(EMBED_DIM)
optimizer = tf.keras.optimizers.Adam(learning_rate=lr_scheduler, beta_1=0.9, beta_2=0.98, epsilon=1e-9) # Changed to tf.keras.optimizers.Adam from keras.optimizers.Adam

# Compile the model
caption_model.compile(optimizer=optimizer, loss=cross_entropy, metrics=["accuracy"])
# caption_model.compile(optimizer=optimizer, loss=cross_entropy, metrics=["accuracy"])

# Fit the model
history = caption_model.fit(train_dataset,
                            epochs=EPOCHS,
                            validation_data=valid_dataset,
                            callbacks=[early_stopping, wandb_callback])

# Compute definitive metrics on train/valid set
train_metrics = caption_model.evaluate(train_dataset, batch_size=BATCH_SIZE)
valid_metrics = caption_model.evaluate(valid_dataset, batch_size=BATCH_SIZE)
wandb.log({'Train Loss': train_metrics[0], 'Train Accuracy': train_metrics[1],
           'Valid Loss': valid_metrics[0], 'Valid Accuracy': valid_metrics[1]})



if TEST_SET:
    test_metrics = caption_model.evaluate(test_dataset, batch_size=BATCH_SIZE)
    wandb.log({'Test Loss': test_metrics[0], 'Test Accuracy': test_metrics[1]})


print("Train Loss = %.4f - Train Accuracy = %.4f" % (train_metrics[0], train_metrics[1]))
print("Valid Loss = %.4f - Valid Accuracy = %.4f" % (valid_metrics[0], valid_metrics[1]))
if TEST_SET:
    print("Test Loss = %.4f - Test Accuracy = %.4f" % (test_metrics[0], test_metrics[1]))

# Save training history under the form of a json file
history_dict = history.history
json.dump(history_dict, open(SAVE_DIR + 'history.json', 'w'))
# Flatten the history dictionary and log each metric separately
# for key, value_list in history.history.items():
#     for epoch, value in enumerate(value_list):
#         wandb.log({f'{key} {epoch}': value})
# # Flatten the history dictionary and log each metric separately
# for key, value_list in history.history.items():
#     for epoch, value in enumerate(value_list):
#         wandb.log({f'{key} {epoch}': value})

# Save weights model
caption_model.save_weights(SAVE_DIR + 'big_model_weights_coco.weights.h5')
run.save(SAVE_DIR + 'big_model_weights_coco.weights.h5')

# Save config model train
config_train = {"IMAGE_SIZE": IMAGE_SIZE,
                "MAX_VOCAB_SIZE" : MAX_VOCAB_SIZE,
                "SEQ_LENGTH" : SEQ_LENGTH,
                "EMBED_DIM" : EMBED_DIM,
                "NUM_HEADS" : NUM_HEADS,
                "FF_DIM" : FF_DIM,
                "BATCH_SIZE" : BATCH_SIZE,
                "EPOCHS" : EPOCHS,
                "VOCAB_SIZE" : VOCAB_SIZE}

json.dump(config_train, open(SAVE_DIR + 'config_train.json', 'w'))

# Save Tokenizer model
save_tokenizer(tokenizer, SAVE_DIR)

run.finish()