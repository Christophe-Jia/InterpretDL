import unittest
import numpy as np

import interpretdl as it
from paddle.vision.models import mobilenet_v2


class TestInfid(unittest.TestCase):

    def test_evaluate(self):
        paddle_model = mobilenet_v2(pretrained=True)
        img_path = 'imgs/catdog.jpg'
        gradcam = it.GradCAMInterpreter(paddle_model, device='cpu')
        exp = gradcam.interpret(
            img_path,
            'features',
            visual=False, 
            save_path=None)
        evaluator = it.Infidelity(paddle_model, device='cpu')
        r = evaluator.evaluate(img_path, exp, resize_to=224, crop_to=224)

        desired = 1.3541696
        delta = max(abs(desired * 1e-3), 1e-8)
        self.assertAlmostEqual(r, desired, delta=delta)

        np.random.seed(42)
        sg = it.SmoothGradInterpreter(paddle_model, device='cpu')
        exp = sg.interpret(
            img_path,            
            n_samples=50,
            noise_amount=0.1,
            visual=False, 
            save_path=None)
        
        r = evaluator.evaluate(img_path, np.mean(np.abs(exp), axis=1), resize_to=224, crop_to=224)
        desired = 1.5331903
        self.assertAlmostEqual(r, desired, delta=delta)

if __name__ == '__main__':
    unittest.main()