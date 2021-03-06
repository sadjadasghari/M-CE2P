import argparse
import os

import cv2
import numpy as np
from PIL import Image as PILImage
from tqdm import tqdm

import torch
import torch.nn as nn
from torch.autograd import Variable
from torch.utils import data

from dataset.datasets_for_mhp import CIHPDataTestSet
from models import Res_CE2P
from refine import refine

# If False, use MHPv2.0 instead.
USE_CIHP_DATA = False # True
# If true, produce colorful label map for better visualization.
USE_PALETTE   = True

IMG_MEAN = np.array((104.00698793, 116.66876762, 122.67891434),
                    dtype=np.float32)

if USE_CIHP_DATA:
  DATA_ROOT       = '/data/datasets/person_attribute/LIP/LIP' #/instance-level_human_parsing' # noqa
  TASK            = os.path.join(DATA_ROOT, 'Play')
  IMAGE_DIR       = os.path.join(TASK, 'Images')
  IMAGE_LIST_PATH = os.path.join(TASK, 'list.txt')
  BOX_DIR         = os.path.join(TASK, 'Boxes')
  SRC_SEGMAP_DIR  = os.path.join(TASK, 'SegMaps')
  MRCNN_WEIGHTS   = './weights/LIP_maskrcnn_edge_200000.pth'
  GT_WEIGHTS      = './weights/LIP_gt_edge_200000.pth'
  GLOBAL_WEIGHTS  = './weights/LIP_global_edge_110000.pth'
  NUM_CLASSES     = 20
else:
  DATA_ROOT       = '/data/datasets/person_attribute/LV-MHP-v2/LV-MHP-v2' # noqa
  TASK            = os.path.join(DATA_ROOT, 'val')
  IMAGE_DIR       = os.path.join(TASK, 'images')
  IMAGE_LIST_PATH = os.path.join(DATA_ROOT, 'list', 'val.txt')
  BOX_DIR         = os.path.join(TASK, 'Boxes')
  SRC_SEGMAP_DIR  = os.path.join(TASK, 'SegMaps')
  MRCNN_WEIGHTS   = './weights/MHP_maskrcnn_edge_150000.pth'
  GT_WEIGHTS      = './weights/MHP_gt_edge_150000.pth'
  GLOBAL_WEIGHTS  = './weights/MHP_global_edge_77000.pth'
  NUM_CLASSES     = 59

OUTPUT_DIR      = './outputs'
# IGNORE_LABEL    = 255
GPU_ID          = '0'


def get_arguments():
  """ Parse all the arguments provided from the CLI.

  Returns:
    A list of parsed arguments.
  """
  parser = argparse.ArgumentParser(description="DeepLabLFOV Network")
  parser.add_argument("--image-dir", type=str, default=IMAGE_DIR,
                      help="Path to the directory containing the \
                      PASCAL VOC dataset.")
  parser.add_argument("--box-dir", type=str, default=BOX_DIR,
                      help="bounding boxes generated by mask-rcnn.")
  parser.add_argument("--image-list", type=str, default=IMAGE_LIST_PATH,
                      help="Path to the file listing the images \
                      in the dataset.")
  # parser.add_argument("--ignore-label", type=int, default=IGNORE_LABEL,
  #                     help="The index of the label to ignore \
  #                     during the training.")
  parser.add_argument("--num-classes", type=int, default=NUM_CLASSES,
                      help="Number of classes to predict \
                      (including background).")
  parser.add_argument("--mrcnn-weights", type=str, default=MRCNN_WEIGHTS,
                      help="Where restore model parameters from. \
                      trained using mask-rcnn generated sub images.")
  parser.add_argument("--gt-weights", type=str, default=GT_WEIGHTS,
                      help="Where restore model parameters from. \
                      trained using ground truth guided sub images.")
  parser.add_argument("--global-weights", type=str, default=GLOBAL_WEIGHTS,
                      help="Where restore model parameters from. \
                      trained using whole images.")
  parser.add_argument("--gpu", type=str, default=GPU_ID,
                      help="choose gpu device.")
  parser.add_argument("--output-dir", type=str, default=OUTPUT_DIR,
                      help="output dir.")
  parser.add_argument("--use-cihp-data", type=bool, default=USE_CIHP_DATA,
                      help="if False, use MHPv2.0 instead.")
  return parser.parse_args()


def get_palette(num_cls):
  """ Returns the color map for visualizing the segmentation mask.

  Inputs:
    =num_cls=
      Number of classes.

  Returns:
      The color map.
  """
  n = num_cls
  palette = [0] * (n * 3)
  for j in range(0, n):
    lab = j
    palette[j * 3 + 0] = 0
    palette[j * 3 + 1] = 0
    palette[j * 3 + 2] = 0
    i = 0
    while lab:
      palette[j * 3 + 0] |= (((lab >> 0) & 1) << (7 - i))
      palette[j * 3 + 1] |= (((lab >> 1) & 1) << (7 - i))
      palette[j * 3 + 2] |= (((lab >> 2) & 1) << (7 - i))
      i += 1
      lab >>= 3
  return palette


def infer(net, image, crop_size, num_classes, use_gpu):
  """ Use deep network to get the segmentation result.
  """
  interp = nn.Upsample(size=crop_size, mode='bilinear')

  if use_gpu:
    prediction = net(Variable(
      torch.from_numpy(image), volatile=True).cuda()
    )
  else:
    prediction = net(Variable(
      torch.from_numpy(image), volatile=True)
    )
  prediction = interp(prediction[1]).cpu().data.numpy().transpose(0, 2, 3, 1)
  return prediction


def predict_one_image(model, image, num_classes, do_filp=True):
  """ Process a single image, maybe whole image or sub iamge.
  """
  if do_filp:
    normal_image = image[0, :, :, :]
    filped_image = image[0, :, :, ::-1]

    nfsingle_out = infer(model,
                         np.stack((normal_image, filped_image)),
                         (473, 473), num_classes,
                         args.gpu != '-1')
    single_out      = np.squeeze(nfsingle_out[0, :, :, :])
    single_out_flip = np.zeros((nfsingle_out.shape[1:4]))

    if USE_CIHP_DATA:
      for c in range(14):
        single_out_flip[:, :, c] = nfsingle_out[1, :, :, c]

      single_out_flip[:, :, 14] = nfsingle_out[1, :, :, 15]
      single_out_flip[:, :, 15] = nfsingle_out[1, :, :, 14]
      single_out_flip[:, :, 16] = nfsingle_out[1, :, :, 17]
      single_out_flip[:, :, 17] = nfsingle_out[1, :, :, 16]
      single_out_flip[:, :, 18] = nfsingle_out[1, :, :, 19]
      single_out_flip[:, :, 19] = nfsingle_out[1, :, :, 18]
      single_out_flip           = single_out_flip[:, ::-1, :]
    else:
      for c in range(59):
        single_out_flip[:, :, c] = nfsingle_out[1, :, :, c]

      single_out_flip[:, :, 5] = nfsingle_out[1, :, :, 6]
      single_out_flip[:, :, 6] = nfsingle_out[1, :, :, 5]
      single_out_flip[:, :, 7] = nfsingle_out[1, :, :, 8]
      single_out_flip[:, :, 8] = nfsingle_out[1, :, :, 7]
      single_out_flip[:, :, 22] = nfsingle_out[1, :, :, 23]
      single_out_flip[:, :, 23] = nfsingle_out[1, :, :, 22]
      single_out_flip[:, :, 24] = nfsingle_out[1, :, :, 25]
      single_out_flip[:, :, 25] = nfsingle_out[1, :, :, 24]
      single_out_flip[:, :, 26] = nfsingle_out[1, :, :, 27]
      single_out_flip[:, :, 27] = nfsingle_out[1, :, :, 26]
      single_out_flip[:, :, 28] = nfsingle_out[1, :, :, 29]
      single_out_flip[:, :, 29] = nfsingle_out[1, :, :, 28]
      single_out_flip[:, :, 30] = nfsingle_out[1, :, :, 31]
      single_out_flip[:, :, 31] = nfsingle_out[1, :, :, 30]
      single_out_flip[:, :, 32] = nfsingle_out[1, :, :, 33]
      single_out_flip[:, :, 33] = nfsingle_out[1, :, :, 32]
      single_out_flip           = single_out_flip[:, ::-1, :]

    # Fuse two outputs
    single_out = np.mean([single_out, single_out_flip], axis=0)
  else:
    single_out = infer(model,
                       image,
                       (473, 473), num_classes,
                       args.gpu != '-1')
    single_out = np.squeeze(single_out)

  return single_out


def predict_whole_image(model,
                        image,
                        whole_image_size,
                        num_classes,
                        do_filp=True):
  """ Segment a whole image without divide into sub images.
  """
  single_out = predict_one_image(model, image, num_classes, do_filp)
  single_out = cv2.resize(single_out,
                            dsize=(whole_image_size[1],
                                   whole_image_size[0]),
                            interpolation=cv2.INTER_LINEAR)
  return single_out


def model_predict_fuse(args, concat=False):
  """ Fuse the results of three models.
  """
  print("Loading model ...")
  mrcnn_model = Res_CE2P(num_classes=args.num_classes)
  mrcnn_model.load_state_dict(torch.load(args.mrcnn_weights))
  mrcnn_model.eval()

  if args.gpu != '-1':
    mrcnn_model.cuda()

  gt_model = Res_CE2P(num_classes=args.num_classes)
  gt_model.load_state_dict(torch.load(args.gt_weights))
  gt_model.eval()

  if args.gpu != '-1':
    gt_model.cuda()

  global_model = Res_CE2P(num_classes=args.num_classes)
  global_model.load_state_dict(torch.load(args.global_weights))
  global_model.eval()

  if args.gpu != '-1':
    global_model.cuda()

  testloader = data.DataLoader(
    CIHPDataTestSet(args.image_dir, args.image_list, args.box_dir, '.jpg',
                    crop_size=(473, 473), mean=IMG_MEAN),
    batch_size=1,
    shuffle=False,
    pin_memory=True
  )

  print("Start inference.")
  pbar = tqdm(testloader)
  for batch in pbar:
    image, name, size, sub_images, boxes = batch

    # Convert to numpy array
    size       = size[0].numpy()
    sub_images = [sub_image.numpy() for sub_image in sub_images]
    image      = image.numpy()

    pbar.set_description('{:<30}'.format('Predicting mrcnn ...'))
    mrcnn_output  = predict_sub_image(mrcnn_model,
                                      size, sub_images, boxes,
                                      args.num_classes)

    pbar.set_description('{:<30}'.format('Predicting gt ...'))
    gt_output     = predict_sub_image(gt_model,
                                      size, sub_images, boxes,
                                      args.num_classes)

    pbar.set_description('{:<30}'.format('Predicting global ...'))
    global_output = predict_whole_image(global_model,
                                        image, size,
                                        args.num_classes)

    #
    # Fuse results.
    #

    # Mask-RCNN + Groundtruth + Global
    pbar.set_description('{:<30}'.format('Fusing mrcnn+gt+global ...'))
    if concat:
      fused_output = np.concatenate(mrcnn_output, gt_output, global_output)
    else:
      fused_output = mrcnn_output + gt_output + global_output

    prefix = 'CIHP' if USE_CIHP_DATA else 'MHPv2'

    result_saving(fused_output,
                  size,
                  os.path.join(args.output_dir, '{}-MRCNN-gt-whole'.format(prefix)),
                  name[0],
                  boxes)

    # # Mask-RCNN + Groundtruth
    # pbar.set_description('{:<30}'.format('Fusing mrcnn+gt ...'))
    # if concat:
    #   fused_output = np.concatenate(mrcnn_output, gt_output)
    # else:
    #   fused_output = mrcnn_output + gt_output

    # result_saving(fused_output,
    #               size,
    #               os.path.join(args.output_dir, '{}-MRCNN-gt'.format(prefix)),
    #               name[0],
    #               boxes)

    # # Mask-RCNN + Global
    # pbar.set_description('{:<30}'.format('Fusing mrcnn+global ...'))
    # if concat:
    #   fused_output = np.concatenate(mrcnn_output, global_output)
    # else:
    #   fused_output = mrcnn_output + global_output

    # result_saving(fused_output,
    #               size,
    #               os.path.join(args.output_dir, '{}-MRCNN-whole'.format(prefix)),
    #               name[0],
    #               boxes)

    # # Groundtruth + Global
    # pbar.set_description('{:<30}'.format('Fusing gt+global ...'))
    # if concat:
    #   fused_output = np.concatenate(gt_output, global_output)
    # else:
    #   fused_output = gt_output + global_output

    # result_saving(fused_output,
    #               size,
    #               os.path.join(args.output_dir, '{}-gt-whole'.format(prefix)),
    #               name[0],
    #               boxes)

    # # Mask-RCNN
    # pbar.set_description('{:<30}'.format('mrcnn ...'))
    # fused_output = mrcnn_output

    # result_saving(fused_output,
    #               size,
    #               os.path.join(args.output_dir, '{}-MRCNN'.format(prefix)),
    #               name[0],
    #               boxes)

    # # Groundtruth
    # pbar.set_description('{:<30}'.format('gt ...'))
    # fused_output = gt_output

    # result_saving(fused_output,
    #               size,
    #               os.path.join(args.output_dir, '{}-gt'.format(prefix)),
    #               name[0],
    #               boxes)

    # # Global
    # pbar.set_description('{:<30}'.format('Fusing global ...'))
    # fused_output = global_output

    # result_saving(fused_output,
    #               size,
    #               os.path.join(args.output_dir, '{}-whole'.format(prefix)),
    #               name[0],
    #               boxes)


def predict_sub_image(model,
                      whole_image_size,
                      sub_images, boxes, num_classes,
                      do_filp=True):
  """ Segment a sequence of sub images of the input image,
  and map the results into one mask.
  """
  output = np.zeros((whole_image_size[0],
                     whole_image_size[1],
                     num_classes),
                    dtype='float')

  output[:, :, 0] = np.inf

  count_predictions = np.zeros((whole_image_size[0],
                                whole_image_size[1],
                                num_classes),
                               dtype='int32')
  assert(len(sub_images) == len(boxes))

  for i in range(len(boxes)):
    single_out = predict_one_image(model, sub_images[i], num_classes, do_filp)
    box = boxes[i]
    single_out = cv2.resize(single_out,
                            dsize=(int(box[2][0]) - int(box[0][0]),
                                   int(box[3][0]) - int(box[1][0])),
                            interpolation=cv2.INTER_LINEAR)

    # Sum up all channels except background(0),
    # and set minimum value to background
    output[int(box[1][0]):int(box[3][0]),
           int(box[0][0]):int(box[2][0]),
           1:] += single_out[:, :, 1:]
    count_predictions[int(box[1][0]):int(box[3][0]),
                      int(box[0][0]):int(box[2][0]),
                      1:] += 1

    output[int(box[1][0]):int(box[3][0]),
           int(box[0][0]):int(box[2][0]),
           0] = np.minimum(output[int(box[1][0]):int(box[3][0]),
                                  int(box[0][0]):int(box[2][0]),
                                  0],
                           single_out[:, :, 0])

  # Caution zero dividing.
  count_predictions[count_predictions == 0] = 1
  return output / count_predictions


def get_instance(cat_gt, human_gt):
  """
  """
  instance_gt = np.zeros_like(cat_gt, dtype=np.uint8)

  num_humans = human_gt.shape[-1]
  class_map = {}

  total_part_num = 0
  for id in range(1, num_humans + 1):
    human_part_label = (
      np.where(human_gt[:, :, id - 1] != 0, 1, 0) * cat_gt
    ).astype(np.uint8)
    part_classes = np.unique(human_part_label)

    exceed = False
    for part_id in part_classes:
      if part_id == 0:
        continue
      total_part_num += 1

      if total_part_num > 255:
        print(
          "total_part_num exceed, return current instance map: {}".format(
            total_part_num)
        )
        exceed = True
        break

      class_map[total_part_num] = part_id
      instance_gt[np.where(human_part_label == part_id)] = total_part_num
    if exceed:
      break

  # Make instance id continous.
  ori_cur_labels      = np.unique(instance_gt)
  total_num_label = len(ori_cur_labels)
  if instance_gt.max() + 1 != total_num_label:
    for label in range(1, total_num_label):
      instance_gt[instance_gt == ori_cur_labels[label]] = label

  final_class_map = {}
  for label in range(1, total_num_label):
    if label >= 1:
      final_class_map[label] = class_map[ori_cur_labels[label]]

  return instance_gt, final_class_map


def compute_confidence(im_name, feature_map, class_map,
                       instance_label, global_label, output_dir):
  """
  """
  conf_file = open(os.path.join(output_dir,
                                im_name + '.txt'), 'w')

  for label in class_map.keys():
    cls = class_map[label]
    confidence = feature_map[:, :, cls].reshape(-1)[
      np.where(instance_label.reshape(-1) == label)
    ]
    confidence = confidence.sum() / len(confidence)
    conf_file.write('{} {}\n'.format(cls, confidence))

  conf_file.close()


def result_saving(res_map, ori_size, output_dir, save_name, boxes):
  """
  """
  if not os.path.exists(output_dir):
    os.makedirs(output_dir)

  global_root   = os.path.join(output_dir, 'global_parsing')
  instance_root = os.path.join(output_dir, 'instance_parsing')
  tag_dir       = os.path.join(output_dir, 'global_tag')
  results_txt   = open(os.path.join(output_dir, 'results.txt'), "a")

  if not os.path.exists(global_root):
    os.makedirs(global_root)
  if not os.path.exists(instance_root):
    os.makedirs(instance_root)
  if not os.path.exists(tag_dir):
    os.makedirs(tag_dir)

  # For visualizing indexed png image.
  palette = get_palette(256)

  res_map  = cv2.resize(res_map, dsize=(ori_size[1], ori_size[0]),
                        interpolation=cv2.INTER_LINEAR)
  seg_pred = np.asarray(np.argmax(res_map, axis=2), dtype=np.uint8)
  tag_pred = np.zeros_like(seg_pred)
  masks    = np.load(os.path.join(SRC_SEGMAP_DIR, save_name + ".npy"))

  instance_pred, class_map = get_instance(seg_pred, masks)
  refine(instance_pred, masks, seg_pred, class_map)

  compute_confidence(save_name, res_map, class_map,
                     instance_pred, seg_pred, instance_root)

  areas = [masks[:, :, i].sum() for i in range(len(boxes))]
  areas = np.asarray(areas)
  sorted_inds = np.argsort(-areas)

  results_txt.write(save_name)
  for index, i in enumerate(sorted_inds):
    idx = np.where(masks[:, :, i] != 0)
    tag_pred[idx] = index + 1
    results_txt.write(' {} {}'.format(str(index + 1), float(boxes[i][4][0])))
  results_txt.write('\n')

  output_im_global   = PILImage.fromarray(seg_pred)
  output_im_instance = PILImage.fromarray(instance_pred)
  output_im_tag   = PILImage.fromarray(tag_pred)
  output_im_global.putpalette(palette)
  output_im_instance.putpalette(palette)
  output_im_tag.putpalette(palette)

  output_im_global.save(os.path.join(global_root,
                                     save_name + '.png'))
  output_im_instance.save(os.path.join(instance_root,
                                       save_name + '.png'))
  output_im_tag.save(os.path.join(tag_dir,
                                  save_name + '.png'))
  results_txt.close()


def main(args):
  """
  """
  model_predict_fuse(args)


if __name__ == '__main__':
  args = get_arguments()
  os.environ["CUDA_VISIBLE_DEVICES"] = args.gpu
  main(args)
