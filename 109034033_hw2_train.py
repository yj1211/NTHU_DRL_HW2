# -*- coding: utf-8 -*-
"""hw2 of DRL.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1Rk4xpM-hZP7cDJHowS6jExV0BV8jTWHa

#Import
"""

!pip install gym==0.23.0
!pip install gym-super-mario-bros
import os
import numpy as np
import scipy
import gym
import pandas as pd
import tensorflow
import torch
import torch.nn as nn
import sys
import time
import pickle
import random
import cv2
from collections import deque
import gym_super_mario_bros
from nes_py.wrappers import JoypadSpace
import gym_super_mario_bros
from gym_super_mario_bros.actions import SIMPLE_MOVEMENT
from gym_super_mario_bros.actions import COMPLEX_MOVEMENT
from gym.wrappers import FrameStack
from gym.wrappers import GrayScaleObservation
from gym.wrappers import ResizeObservation
from gym.wrappers import RecordVideo

from google.colab import drive
drive.mount('/content/drive')

"""#Parameter"""

training_steps=100000
warmup_steps=15000
buffer_capacity=20000
batch_size=16
gamma=0.99
update_target_freq=8
lr=0.0025
eval_interval=100
max_memory_size=30000
dropout=0.2
exploration_max=1.0,
exploration_min=0.02,
exploration_decay=0.99

"""#Class"""

#create neural network
class Network(nn.Module):
    def __init__(self, num_classes=12):
        super().__init__()

        #convolution layers
        self.cnn = nn.Sequential(nn.Conv2d(3, 32, kernel_size=8, stride=4),nn.ReLU(True),nn.Conv2d(32, 64, kernel_size=4, stride=2),nn.ReLU(True),)
        self.classifier = nn.Sequential(nn.Linear(9*9*64, 128),nn.ReLU(True),nn.Linear(128, num_classes) )
        self._initialize_weights()

    #forward pass of the network
    def forward(self, x):
        x = x.float() / 255.
        x = self.cnn(x)
        x = torch.flatten(x, start_dim=1)
        x = self.classifier(x)
        return x

    #depend on what neural network to initialize weights
    def _initialize_weights(self):
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
                if m.bias is not None:
                    nn.init.constant_(m.bias, 0.0)
            elif isinstance(m, nn.BatchNorm2d):
                nn.init.constant_(m.weight, 1.0)
                nn.init.constant_(m.bias, 0.0)
            elif isinstance(m, nn.Linear):
                nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
                nn.init.constant_(m.bias, 0.0)

#a important way to review the old experience to reinforce learning
class ReplayMemory(object):
    def __init__(self, capacity):

        #use queue methods to save new transitions and throw old transitions
        self.buffer = deque(maxlen=capacity)
    def __len__(self):
        return len(self.buffer)
    def append(self, *transition):
        self.buffer.append(tuple(map(tuple,transition)))

    #randomly choose transitions to return tensors
    def sample(self, batch_size, device):
        transitions = random.sample(self.buffer, batch_size)
        return (torch.tensor(np.asarray(x), dtype=torch.float, device=device) for x in zip(*transitions))

"""#Environment"""

#create video by collecting the whole states
'''
# Define the codec and create VideoWriter object
fourcc = cv2.VideoWriter_fourcc(*'mp4v')
out = cv2.VideoWriter('output.mp4', fourcc, 30.0, (256, 240))

for i in range(len(store_state)):
    out.write(store_state[i])

# Release everything if job is finished
out.release()
'''

class Agent:
  def __init__(self):
    #cpu for final test, gpu for training
    self.device = 'cuda' if torch.cuda.is_available() else 'cpu'

    #create neural network
    self.behavior_net= Network()
    self.target_net= Network()
    self.behavior_net=self.behavior_net.to(self.device)
    self.target_net=self.target_net.to(self.device)

    #Adam is the best optimizer
    self.optim=torch.optim.Adam(self.behavior_net.parameters(),lr=lr)

    #adding and removing item to review the old experience
    self.buffer= ReplayMemory(buffer_capacity)


    #create enviroment
    self.env = gym_super_mario_bros.make('SuperMarioBros-v0')
    self.env = JoypadSpace(self.env, COMPLEX_MOVEMENT)

    #wrap enviorment
    self.env = FrameStack(GrayScaleObservation(ResizeObservation(self.env,84),keep_dim=False), num_stack = 3)

    self.action_space = self.env.action_space

  #use epsilon to decide action to discover
  def act(self, observation, epsilon=0):
    #randomly choose action
    if random.random() < 0:
      action=self.action_space.sample()

    #choose action by model
    else:
      with torch.no_grad(): #means no calculate gradients
        obs= np.asarray(observation).copy()
        obs= torch.unsqueeze(torch.tensor(obs, dtype=float, device=self.device), 0)
        q_values=self.behavior_net(obs)
        action=torch.argmax(q_values)
        action=action.item()
      return action

  def update_behavior_net(self):
    state, action, reward, next_state, done = self.buffer.sample(batch_size, self.device)
    q_values = self.behavior_net(state)[range(action.shape[0]), action.int().view(-1)]
    with torch.no_grad():
        max_q, _ = torch.max(self.target_net(next_state), 1)
        done = done.squeeze(1)
        reward = reward.squeeze(1)
        max_q[done.bool()] = 0.0

        #calculate q_target
        q_target =reward+max_q*gamma

    #simple way to calculate loss
    crit = nn.MSELoss()
    loss = crit(q_values, q_target)

    self.optim.zero_grad()

    #backward gradient
    loss.backward()
    self.optim.step()

  def train(self):
    ep_idx = 0
    total_time_step = 0
    while(total_time_step <= training_steps):

        #enviroment reset
        ob = self.env.reset()

        #episode
        ep_rew = 0 #reward num
        ep_len = 0  #action num
        ep_idx += 1 #loops num

        #warmup at the beginning
        while True:
            if total_time_step % 5000 == 0:
                print(f"step {total_time_step}")
            if total_time_step < warmup_steps:
                action = self.action_space.sample()

            #decay the epsilon, like the aging of priority in OS
            else:
                epsilon = max(1-total_time_step/100000, 0.1)
                action = self.act(ob, epsilon = epsilon)


            next_ob, rew, term, info = self.env.step(action)

            #save action and reward
            self.buffer.append(ob, [action], [rew], next_ob, [int(term)])


            #after warmup
            if total_time_step >= warmup_steps:
                self.update_behavior_net()

                #sync
                if total_time_step % update_target_freq == 0:
                    self.target_net.load_state_dict(self.behavior_net.state_dict()) ##update target net
            ep_rew += rew
            ep_len += 1

            #tell scores
            if term :
                print(f"episode: {ep_idx} score: {ep_rew} len: {ep_len}, step:{total_time_step}")
                break
            ob = next_ob
            total_time_step += 1

        #evaluate
        if ep_idx % eval_interval == 0:
            print("Episode {} score = {}".format(ep_idx, ep_rew))

    #save model
    torch.save(self.behavior_net.state_dict(), "DQN.pt")

if __name__ == "__main__":
    print("start")
    agent = Agent()
    agent.train()