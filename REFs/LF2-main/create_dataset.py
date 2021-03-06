from __future__ import print_function, absolute_import
import os
os.environ['CUDA_VISIBLE_DEVICES']='0'

import warnings
warnings.filterwarnings('ignore')

import argparse
import os.path as osp
import random
import numpy as np

import sys
sys.path.append('..')

import torch
from torch import nn
from torch.backends import cudnn
from torch.utils.data import DataLoader

from reid import datasets
from reid import models
#from reid.evaluators import Evaluator
from reid.evaluation_custom.clustering_unlabeled import DSCluster
from reid.utils.data import transforms as T
from reid.utils.data.preprocessor import Preprocessor
from reid.utils.logging import Logger
from reid.utils.serialization import load_checkpoint
from reid.models.resnet import Encoder

device_ids = [0,1]

def get_data(name, data_dir, height, width, batch_size, workers):
    root = osp.join(data_dir)
    dataset = datasets.create(name, root)

    normalizer = T.Normalize(mean=[0.485, 0.456, 0.406],
                             std=[0.229, 0.224, 0.225])
    test_transformer = T.Compose([
             T.Resize((height, width), interpolation=3),
             T.ToTensor(),
             normalizer
         ])
    test_loader = DataLoader(
        Preprocessor(list(set(dataset.query) | set(dataset.gallery)),
                     root=dataset.images_dir, transform=test_transformer),
        batch_size=batch_size, num_workers=workers,
        shuffle=False, pin_memory=True)
    return dataset, test_loader


def create_model(args, extract_feat_):  
    arch = args.arch
    model_student = models.create(arch, num_features=args.features, dropout=args.dropout, num_classes=args.num_clusters, \
                                  num_split=args.split_parts, extract_feat=extract_feat_).cuda()
    model_teacher = models.create(arch, num_features=args.features, dropout=args.dropout, num_classes=args.num_clusters,\
                                  num_split=args.split_parts, extract_feat=extract_feat_).cuda()
    model_student = nn.DataParallel(model_student)  
    model_teacher = nn.DataParallel(model_teacher)

    for param in model_teacher.parameters():
        param.detach_()

    return model_student, model_teacher


def main():
    args = parser.parse_args()
    if args.seed is not None:
        random.seed(args.seed)
        np.random.seed(args.seed)
        torch.manual_seed(args.seed)
        cudnn.deterministic = True
    main_worker(args)


def main_worker(args):
    cudnn.benchmark = True

    log_dir = osp.dirname(args.resume)
    sys.stdout = Logger(osp.join(log_dir, 'log_test.txt'))
    print("==========\nArgs:{}\n==========".format(args))

    # Create data loaders
    dataset_target, test_loader_target = \
        get_data(args.dataset_target, args.data_dir, args.height,
                 args.width, args.batch_size, args.workers)

    # Create model
    model_student, model_teacher = create_model(args, False)
    encoder = Encoder(model_student, model_teacher)
    
    # Load from checkpoint
    checkpoint = load_checkpoint(args.resume)
    encoder.load_state_dict(checkpoint['state_dict'])
    start_epoch = checkpoint['epoch']
    best_mAP = checkpoint['best_mAP']
    print("=> Checkpoint of epoch {}  best mAP {:.1%}".format(start_epoch, best_mAP))

    # Evaluator
    cluster = DSCluster(model, args)
    print("Cluster and create new ds the target domain of {}:".format(args.dataset_target))
    cluster.evaluate(test_loader_target, dataset_target.query, dataset_target.gallery, 
            rerank=args.rerank)
    return

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Testing the model")
    # data
    parser.add_argument('-dt', '--dataset-target', type=str,  default='market',choices=datasets.names())
    parser.add_argument('-b', '--batch-size', type=int, default=64)
    parser.add_argument('-j', '--workers', type=int, default=4)
    parser.add_argument('--num-clusters', type=int, default=700)
    parser.add_argument('--height', type=int, default=256, help="input height")
    parser.add_argument('--width', type=int, default=128, help="input width")
    # model
    parser.add_argument('-a', '--arch', type=str,  default='resnet50')
    parser.add_argument('--features', type=int, default=0)
    parser.add_argument('--dropout', type=float, default=0)
    parser.add_argument('--split-parts', type=int, default=2)       # splitted parts
    # testing configs
    parser.add_argument('--resume', type=str, metavar='PATH', default='logs_d2m/model_best.pth.tar')
    parser.add_argument('--hard_sample', action='store_true', help="evaluation only, strictly choose samples in clusters")
    parser.add_argument('--rerank', action='store_true', help="evaluation only")
    parser.add_argument('--clusters', type=int, default=0, help="number cluster for kmeans")
    parser.add_argument('--seed', type=int, default=1)
    # path
    working_dir = osp.dirname(osp.abspath(__file__))
    parser.add_argument('--data-dir', type=str, metavar='PATH', default='/home/dj/reid/data')
    main()
