import numpy as np

from tqdm import tqdm
from .abc_interpreter import InputGradientInterpreter
from ..data_processor.readers import images_transform_pipeline, preprocess_save_path
from ..data_processor.visualizer import explanation_to_vis, show_vis_explanation, save_image


class SmoothGradInterpreter(InputGradientInterpreter):
    """
    Smooth Gradients Interpreter.

    For input gradient based interpreters, the target issue is generally the vanilla input gradient's noises.
    The basic idea of reducing the noises is to use different similar inputs to get the input gradients and 
    do the average. 

    Smooth Gradients method solves the problem of meaningless local variations in partial derivatives
    by adding random noise to the inputs multiple times and take the average of the gradients.

    More details regarding the Smooth Gradients method can be found in the original paper:
    http://arxiv.org/abs/1706.03825.
    """

    def __init__(self, paddle_model: callable, device: str = 'gpu:0', use_cuda=None):
        """

        Args:
            paddle_model (callable): A model with ``forward`` and possibly ``backward`` functions.
            device (str): The device used for running `paddle_model`, options: ``cpu``, ``gpu:0``, ``gpu:1`` etc.
        """

        InputGradientInterpreter.__init__(self, paddle_model, device, use_cuda)

    def interpret(self,
                  inputs: str or list(str) or np.ndarray,
                  labels: list or np.ndarray = None,
                  noise_amount: int = 0.1,
                  n_samples: int = 50,
                  resize_to: int = 224,
                  crop_to: int = None,
                  visual: bool = True,
                  save_path: str = None) -> np.ndarray:
        """The technical details of the SmoothGrad method are described as follows:
        SmoothGrad generates ``n_samples`` noised inputs, with the noise scale of ``noise_amount``, and then computes 
        the gradients w.r.t. these noised inputs. The final explanation is averaged gradients.

        Args:
            inputs (strorlist): The input image filepath or a list of filepaths or numpy array of read images.
            labels (listornp.ndarray, optional): The target labels to analyze. The number of labels should be equal 
                to the number of images. If None, the most likely label for each image will be used. Default: None.
            noise_amount (int, optional): Noise level of added noise to the image. The std of Gaussian random noise 
                is noise_amount * (x_max - x_min). Default: 0.1.
            n_samples (int, optional): The number of new images generated by adding noise. Default: 50.
            resize_to (int, optional): Images will be rescaled with the shorter edge being `resize_to`. 
                Defaults to 224.
            crop_to (int, optional): After resize, images will be center cropped to a square image with the size 
                `crop_to`. If None, no crop will be performed. Defaults to None.
            visual (bool, optional): Whether or not to visualize the processed image. Default: True.
            save_path (str, optional): The filepath(s) to save the processed image(s). If None, the image will not be 
                saved. Default: None.

        Returns:
            np.ndarray: the explanation result.
        """

        imgs, data = images_transform_pipeline(inputs, resize_to, crop_to)
        # print(imgs.shape, data.shape, imgs.dtype, data.dtype)  # (1, 224, 224, 3) (1, 3, 224, 224) uint8 float32

        bsz = len(data)

        self._build_predict_fn(gradient_of='probability')

        # obtain the labels (and initialization).
        if labels is None:
            _, preds = self.predict_fn(data, None)
            labels = preds
        labels = np.array(labels).reshape((bsz, ))

        # SmoothGrad
        max_axis = tuple(np.arange(1, data.ndim))
        stds = noise_amount * (np.max(data, axis=max_axis) - np.min(data, axis=max_axis))

        total_gradients = np.zeros_like(data)
        for i in tqdm(range(n_samples), leave=True, position=0):
            noise = np.concatenate(
                [np.float32(np.random.normal(0.0, stds[j], (1, ) + tuple(d.shape))) for j, d in enumerate(data)])
            data_noised = data + noise
            gradients, _ = self.predict_fn(data_noised, labels)
            total_gradients += gradients

        avg_gradients = total_gradients / n_samples

        # visualize and save image.
        if save_path is None and not visual:
            # no need to visualize or save explanation results.
            pass
        else:
            save_path = preprocess_save_path(save_path, bsz)
            for i in range(bsz):
                # print(imgs[i].shape, avg_gradients[i].shape)
                vis_explanation = explanation_to_vis(imgs[i],
                                                     np.abs(avg_gradients[i]).sum(0),
                                                     style='overlay_grayscale')
                if visual:
                    show_vis_explanation(vis_explanation)
                if save_path[i] is not None:
                    save_image(save_path[i], vis_explanation)

        # intermediate results, for possible further usages.
        self.labels = labels

        return avg_gradients
