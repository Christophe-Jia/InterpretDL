import typing
from typing import Any, Callable, List, Tuple, Union

from interpretdl.interpreter.abc_interpreter import Interpreter
from interpretdl.data_processor.readers import preprocess_image, read_image
from interpretdl.data_processor.visualizer import visualize_ig

import IPython.display as display
import cv2
import numpy as np
import paddle.fluid as fluid
import os, sys
from PIL import Image

class IntGradInterpreter(Interpreter):
    """
    Integrated Gradients Interpreter.

    More details regarding the Integrated Gradients method can be found in the original paper:
    http://proceedings.mlr.press/v70/sundararajan17a/sundararajan17a.pdf
    """

    def __init__(self, predict_fn, trained_model_path, class_num, use_cuda, model_input_shape = [3, 224, 224]) -> None:
        """
        Initialize the IntGradInterpreter

        Args:
            predict_fn: A user-defined function that gives access to model predictions. It takes the following arguments:
                    - data: Data input.
                    - alpha: A scalar for calculating the path integral
                    - baseline: The baseline input.
                    example:
                        def predict_fn(data, alpha, baseline):
                            import paddle.fluid as fluid
                            class_num = 1000
                            image_input = baseline + alpha * data
                            model = ResNet50()
                            logits = model.net(input=image_input, class_dim=class_num)

                            probs = fluid.layers.softmax(logits, axis=-1)
                            return image_input, probs
            trained_model_path: The pretrained model directory.
            class_num: Number of classes for the model.
            task: Can either be 'cv' or 'nlp'
            use_cuda: Whether or not to use cuda.
            model_input_shape: The input shape of the model

        Returns:
        """
        Interpreter.__init__(self)
        self.predict_fn = predict_fn
        self.trained_model_path = trained_model_path
        self.class_num = class_num
        self.use_cuda = use_cuda
        self.model_input_shape = model_input_shape

    def set_params(self):
        """
        Set parameters for the interpreter.
        """
        pass

    def interpret(self, data, label = None, baseline = None, steps = 50, num_random_trials=10, visual=True, save_path=None):
        """
        Main function of the interpreter.

        Args:
            data: If task is 'cv', input the image filepath; if task is 'nlp', input a sequence of word ids.
            label: The target label to analyze. If None, the most likely label will be used.
            baseline: The baseline input. If None, all zeros will be used. If 'random', random Guassian initialization will be used.
            setps: number of steps in the Riemman approximation of the integral
            num_random_trials: number of random initializations to take average in the end.
            visual: Whether or not to visualize the processed image.
            save_path: The filepath to save the processed image. If None, the image will not be saved.

        Returns:
        """
        startup_prog = fluid.Program()
        main_program = fluid.Program()
        if isinstance(data, str) or len(np.array(data).shape) > 2:
            input_type = 'cv'
        else:
            input_type = 'nlp'
            baseline = None
        
        # Read in image
        if isinstance(data, str):
            with open(data, 'rb') as f:
                org = Image.open(f)
                org = org.convert('RGB')
                org = np.array(org)
                img = read_image(data, crop_size = self.model_input_shape[1])
                data = preprocess_image(img)    
                
        data_type = np.array(data).dtype
        
        with fluid.program_guard(main_program, startup_prog):
            with fluid.unique_name.guard():
                
                data_op = fluid.data(name='data', shape=[1] + self.model_input_shape, dtype=data_type)
                label_op = fluid.layers.data(name='label', shape=[1], dtype='int64')
                alpha_op = fluid.layers.data(name='alpha', shape=[1], dtype='double')
                
                if baseline == 'random':
                    x_baseline = fluid.layers.gaussian_random([1] + self.model_input_shape, dtype=data_type)
                else:
                    x_baseline = fluid.layers.zeros_like(data_op)
                    
                x_diff = data_op - x_baseline
                
                x_step, probs = self.predict_fn(x_diff, alpha_op, x_baseline)
                
                for op in main_program.global_block().ops:
                    if op.type == 'batch_norm':
                        op._set_attr('use_global_stats', True)

                one_hot = fluid.layers.one_hot(label_op, self.class_num)
                one_hot = fluid.layers.elementwise_mul(probs, one_hot)
                target_category_loss = fluid.layers.reduce_sum(one_hot)

                p_g_list = fluid.backward.append_backward(target_category_loss)

                gradients_map = fluid.gradients(one_hot, x_step)[0]
         
        if self.use_cuda:
            gpu_id = int(os.environ.get('FLAGS_selected_gpus', 0))
            place = fluid.CUDAPlace(gpu_id)
        else:
            place = fluid.CPUPlace()
        exe = fluid.Executor(place)

        fluid.io.load_persistables(exe, self.trained_model_path, main_program)
        


        # if label is None, let it be the most likely label
        
        gradients, out, data_diff = exe.run(main_program, feed={
                'data': data,
                'label': np.array([[0]]),
                'alpha': np.array([[float(1)]]),
            }, fetch_list=[gradients_map, probs, x_step], return_numpy = False)
        
        if label is None:
            label = np.argmax(out[0])
            
        gradients_list = []
        
        if baseline is None:
            num_random_trials = 1
            
        for i in range(num_random_trials):
            total_gradients = np.zeros_like(gradients)
            for alpha in np.linspace(0, 1, steps):
                [gradients] = exe.run(main_program, feed={
                        'data': data,
                        'label': np.array([[label]]),
                        'alpha': np.array([[alpha]]),
                    }, fetch_list=[gradients_map], return_numpy = False)
                total_gradients += np.array(gradients)
            ig_gradients = total_gradients * np.array(data_diff) / steps
            gradients_list.append(ig_gradients)
        avg_gradients = np.average(np.array(gradients_list), axis=0)
        
        if input_type == 'cv':
            visualize_ig(avg_gradients, img, visual, save_path)
            
        return avg_gradients