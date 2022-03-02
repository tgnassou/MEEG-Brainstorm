#!/opt/anaconda3/bin/python

"""
This script is used to train and test the model. 
Usage: type "from Train import <class>" to use one of its class.
       type "from Train import <function>" to use one of its function.
Contributors: Ambroise Odonnat.
"""

import json
import torch

import numpy as np

from torch.autograd import Variable
from sklearn.metrics import f1_score

from data import Data
from dataloader import train_test_dataset, get_dataloader
from Model import Transformer
from utils import check_balance

import logging
logging.getLogger().setLevel(logging.INFO)
log = logging.getLogger(__name__)


class Trans():
    
    def __init__(self, folder, channel_fname, wanted_event_label,list_channel_type, binary_classification, selected_rows,\
                 train_size, validation_size, batch_size, num_workers, random_state, shuffle, balanced,\
                 display_balance = True):
        
        """    
        Args:
            folder (list): List of paths to trial files (matlab dictionnaries),
            channel_fname (str): Path to channel file (matlab dictionnary),
            wanted_event_label (str): Annotation of wanted event,
            list_channel_type (list): List of the types of channels we want ,
            binary_classification (bool): Labellize trials in two classes as seizure/no seizure 
                                          instead of taking the number of seizures as label,
            selected_rows (int): Number of rows of each sub-spatial filter selected to create spatial filter,
            train_size (int): Size of the train set before separation into train and validation set,
            validation_size (int): Size of the validation set,
            batch_size (int): Batch size,
            num_workers (int): Number of preprocessed batches to gain computation time (consumes memory),
            random_state (int): Seed to insure reproductibility during shuffle in train_test_split function,
            shuffle (bool): Shuffle the data during train_test_split,
            balanced (bool): Use a weighted sampler during creation of dataloaders (for training and validation),
            display_balance (bool): Check that training and validation sets are balanced.
                                    
                                          
        """
        
        # Data format
        self.Tensor = torch.FloatTensor
        self.LongTensor = torch.LongTensor
        
        # Recover dataset
        log.info(' Get Dataset')
        self.dataset = Data(folder,channel_fname,wanted_event_label, list_channel_type,binary_classification, selected_rows)
        self.allData, self.allLabels, self.allSpikeTimePoints, self.allTimes = self.dataset.csp_data()
        
        
        # Recover dataloader
        log.info(' Get Dataloader')
        
        # Split data and labels in train, validation and test sets
        data_train, labels_train, data_test, labels_test = train_test_dataset(self.allData, self.allLabels,\
                                                                   train_size, shuffle, random_state)
        
        new_train_size = 1 - validation_size/train_size
        data_train, labels_train, data_val, labels_val = train_test_dataset(data_train, labels_train,\
                                                                   new_train_size, shuffle, random_state)
        
        data_train = np.expand_dims(data_train, axis = 1)
        data_val = np.expand_dims(data_val, axis = 1)
        data_test = np.expand_dims(data_test, axis = 1)
        
        self.train_dataloader = get_dataloader(data_train, labels_train, batch_size, num_workers, balanced)
        self.validation_dataloader = get_dataloader(data_val, labels_val, batch_size, num_workers, balanced)
        self.test_dataloader = get_dataloader(data_test, labels_test, batch_size, num_workers, balanced = False)

        # Check that train_loader is balanced
        if display_balance:
            log.info(' Check balance')
            print(check_balance(self.train_dataloader, np.unique(labels_train).shape[0], 1, True))
            print(check_balance(self.validation_dataloader, np.unique(labels_val).shape[0], 1, True))
            print(check_balance(self.test_dataloader, np.unique(labels_test).shape[0], 1, True))
        

    def train(self, model_config, optimizer_config, n_epochs, mix_up, BETA,\
              model_path, optimizer_path, config_model_path, config_optimizer_path, save):

        """
        Train the model and keep accuracy and F1 scores on the validation set.

        Args:
            model_config (dict): Dictionnary containing Transformer Model hyperparamaters,
            optimizer_config (dict): Dictionnary containing optimizer paramaters,
            n_eppchs (int): Number of epochs,
            mix_up (boo): Apply a mix-up strategy to help the model generalize,
            BETA (float): Parameter of the BETA law used in mix-up strategy,
            model_path (str): Path to save the model parameters,
            optimizer_path (str): Path to save the opimizer parameters,
            config_model_path (str): Path to save the model_config,
            config_optimizer_path (str): Path to save the optimizer_config,
            save (bool): Save information into the previous paths.

        Returns:
            tuple: train_info (dict): Values of loss, accuracy, F1 score on training set,
                   test_info (dict): Values of loss, accuracy, f1 score on validation set,
                   bestAcc (float): Best accuracy on validation set,
                   averAcc (float) Average accuracy on validation set,
                   bestF1 (float): Best F1 score on validation set,
                   averF1 (float) Average F1 score on validation set,
                   Y_true_acc (array): labels corresponding to best accuracy
                   Y_pred_acc (array): prediciton corresponding to best accuracy,
                   Y_true_F1 (array): labels corresponding to best F1 score,
                   Y_pred_F1 (array): prediciton corresponding to best F1 score.
        """
        
        # Define model
        self.model = Transformer(**model_config)
        
        # Move to gpu if available
        device = "cpu"
        if torch.cuda.is_available():
            device = "cuda:0"
            if torch.cuda.device_count() > 1:
                self.model = nn.DataParallel(self.model)
        self.model.to(device)

        # Define loss
        self.criterion_cls = torch.nn.CrossEntropyLoss()
                
        # Define optimizer
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr = optimizer_config['lr'],\
                                          betas=(optimizer_config['b1'], optimizer_config['b2']))
        
        bestAcc = 0
        averAcc = 0
        bestF1 = 0
        averF1 = 0
        train_info = dict((e,{"Loss": 0, "Accuracy": 0, "F1_score": 0}) for e in range(n_epochs))
        test_info = dict((e,{"Loss": 0, "Accuracy": 0, "F1_score": 0}) for e in range(n_epochs))
        best_epochs_acc = 0
        best_epochs_F1 = 0
        num = 0
        Y_true_acc = []
        Y_pred_acc = [] 
        Y_true_F1 = []
        Y_pred_F1 = []   
      
        for e in range(n_epochs):
            
            # Train the model
            self.model.train()
            correct, total = 0,0
            weighted_f1_train, f1_train = [],[]
            for i, (data, labels) in enumerate(self.train_dataloader):
                                
                if mix_up:
                    
                    # Apply a mix-up strategy for data augmentation as adviced here '<https://forums.fast.ai/t/mixup-data-augmentation/22764>'

                    # Roll a copy of the batch
                    roll_factor =  torch.randint(0, data.shape[0], (1,)).item()
                    rolled_data = torch.roll(data, roll_factor, dims=0)        
                    rolled_labels = torch.roll(labels, roll_factor, dims=0)  

                    # Create a tensor of lambdas sampled from the beta distribution
                    lambdas = np.random.beta(BETA, BETA, data.shape[0])

                    # trick from here https://forums.fast.ai/t/mixup-data-augmentation/22764
                    lambdas = torch.reshape(torch.tensor(np.maximum(lambdas, 1-lambdas)), (-1,1,1,1))

                    # Mix samples
                    mix_data = lambdas*data + (1-lambdas)*rolled_data

                    # Recover data, labels
                    mix_data = Variable(mix_data.type(self.Tensor))
                    data = Variable(data.type(self.Tensor))
                    labels = Variable(labels.type(self.LongTensor))
                    rolled_labels = Variable(rolled_labels.type(self.LongTensor))
                    mix_data, labels, rolled_labels = mix_data.to(device), labels.to(device), rolled_labels.to(device)
                    
                    # zero the parameter gradients
                    self.optimizer.zero_grad()

                    # forward + backward
                    _, mix_outputs = self.model(mix_data)
                    loss = lambdas.squeeze()*self.criterion_cls(mix_outputs, labels) + (1-lambdas.squeeze())*self.criterion_cls(mix_outputs, rolled_labels)
                    loss = loss.sum()
                    loss.backward()
                    
                    # Optimize
                    self.optimizer.step()
                    
                    # Recover accurate prediction and F1 scores
                    y_pred = torch.max(mix_outputs.data, 1)[1]
                    total += labels.size(0)
                    correct += (y_pred == labels).sum().item()
                    weighted_f1_train.append(f1_score(labels, y_pred, average = 'weighted'))
                    f1_train.append(f1_score(labels, y_pred, average = 'macro'))
                else:
                    data = Variable(data.type(self.Tensor))
                    labels = Variable(labels.type(self.LongTensor))
                    data, labels = data.to(device), labels.to(device)
                    
                    # zero the parameter gradients
                    self.optimizer.zero_grad()

                    # forward + backward
                    _, outputs = self.model(data)
                    loss = self.criterion_cls(outputs, labels)
                    loss.backward()
                    
                    # Optimize
                    self.optimizer.step()
                    
                    # Recover accurate prediction and F1 score
                    y_pred = torch.max(outputs.data, 1)[1]
                    total += labels.size(0)
                    correct += (y_pred == labels).sum().item()
                    f1_train.append(f1_score(labels, y_pred, average = 'macro'))
            
            # Recover accuracy and F1 score 
            train_acc = 100 * correct // total
            train_info[e]["Loss"] = loss.detach().numpy()
            train_info[e]["Accuracy"] = train_acc
            train_info[e]["F1_score"] = np.mean(f1_train)
                
            # Evaluate the model
            self.model.eval()
            test_correct, test_total = 0,0
            weighted_f1_test, f1_test = [],[]
            Predictions = []
            Labels = []
            
            for j, (test_data, test_labels) in enumerate(self.validation_dataloader):

                # Recover data, labels
                test_data = Variable(test_data.type(self.Tensor))
                test_labels = Variable(test_labels.type(self.LongTensor))

                # Recover outputs
                _, test_outputs = self.model(test_data)
                test_loss = self.criterion_cls(test_outputs, test_labels)

                    # Recover accurate prediction and F1 scores
                test_y_pred = torch.max(test_outputs, 1)[1]
                test_total += test_labels.size(0)
                test_correct += (test_y_pred == test_labels).sum().item()
                f1_test.append(f1_score(test_labels, test_y_pred, average = 'macro'))

                # Recover labels and prediction
                Predictions.append(test_y_pred.detach().numpy())
                Labels.append(test_labels.detach().numpy())

            # Recover accuracy and F1 score
            test_acc = 100 * test_correct // test_total
            test_info[e]["Loss"] = test_loss.detach().numpy()
            test_info[e]["Accuracy"] = test_acc
            test_info[e]["F1_score"] = np.mean(f1_test)

            
            num+=1
            averAcc = averAcc + test_acc
            averF1 = averF1 + np.mean(f1_test)
            
            if test_acc > bestAcc:
                bestAcc = test_acc
                best_epochs_acc = e
                Y_true_acc = Predictions
                Y_pred_acc = Labels
                
            if np.mean(f1_test) > bestF1:
                bestF1 = np.mean(f1_test)
                best_epochs_F1 = e
                Y_true_F1 = Predictions
                Y_pred_F1 = Labels

        if num > 0:
            averAcc = averAcc / num
            averF1 = averF1 / num
        print('The average accuracy is:', averAcc)
        print('The best accuracy is:', bestAcc)
        print('The average F1 score is:', averF1)
        print('The best F1 score is:', bestF1)
        
        if save:
            log.info("Saving config files")
            json.dump(model_config, open( config_model_path, 'w' ) )
            json.dump(optimizer_config, open( config_optimizer_path, 'w' ) )
            
            log.info("Saving parameters")
            torch.save(self.model.state_dict(), model_path)
            torch.save(self.optimizer.state_dict(), optimizer_path)
            
        
        
        return train_info, test_info, bestAcc, averAcc, bestF1, averF1, Y_true_acc, Y_pred_acc, Y_true_F1, Y_pred_F1
    
    
    def evaluate(self, model_config_path, optimizer_config_path, model_path, optimizer_path):

        """
        Evaluate a model on test set.

        Args:
            model_config_path (str): Path to recover model_config dictionnary,
            optimizer_config_path (str): Path to recover optimizer_config dictionnary,
            model_path (str): Path to recover model hyperparameters,
            optimizer_path (str): Path to recover optimizer parameters.

        Returns:
            tuple: accuracy (float): Average accuracy on the test set,
                   F1 score (float): Average F1 score on the test set.
        """
        
        # Recover config files
        with open(model_config_path) as f:
            model_config = json.loads(f.read())
            
        with open(optimizer_config_path) as f:
            optimizer_config = json.loads(f.read())
            
        # Load model parameters
        model = Transformer(**model_config)
        model.load_state_dict(torch.load(model_path))
        
        # Move to gpu if available
        device = "cpu"
        if torch.cuda.is_available():
            device = "cuda:0"
            if torch.cuda.device_count() > 1:
                model = nn.DataParallel(model)
        model.to(device)
        
        # Load optimizer parameters
        optimizer = torch.optim.Adam(model.parameters(), lr = optimizer_config['lr'],\
                                          betas=(optimizer_config['b1'], optimizer_config['b2']))        
        optimizer.load_state_dict(torch.load(optimizer_path))
        
        # Initialize accuracy
        correct = 0
        total = 0
        f1_test = []
        with torch.no_grad():
            for data, labels in self.test_dataloader:
                data = Variable(data.type(self.Tensor))
                labels = Variable(labels.type(self.LongTensor))
                data, labels = data.to(device), labels.to(device)
                _, outputs = model(data)
                predicted = torch.max(outputs.data, 1)[1]
                total += labels.size(0)
                correct += (predicted == labels).sum().item()
                f1_test.append(f1_score(labels, predicted, average = 'macro'))

        accuracy = correct / total * 100
        F1_score = np.mean(f1_test)
        return accuracy , F1_score
        
        
        