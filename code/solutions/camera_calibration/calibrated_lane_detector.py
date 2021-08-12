import numpy as np
from ..lane_detection.lane_detector import LaneDetector
from ..lane_detection.camera_geometry import CameraGeometry


def get_intersection(line1, line2):
    m1, c1 = line1
    m2, c2 = line2
    if m1 == m2:
        return None
    u_i = (c2 - c1) / (m1 - m2)
    v_i = m1*u_i + c1
    return u_i, v_i

def get_py_from_vp(u_i, v_i, K):
    p_infinity = np.array([u_i, v_i, 1])
    K_inv = np.linalg.inv(K)
    r3 = K_inv @ p_infinity    
    r3 /= np.linalg.norm(r3)
    yaw = -np.arctan2(r3[0], r3[2])
    pitch = np.arcsin(r3[1])    
    
    return pitch, yaw

class CalibratedLaneDetector(LaneDetector):
    def __init__(self, calib_cut_v = 200, cam_geom=CameraGeometry(), model_path='./fastai_model.pth'):
        # call parent class constructor
        super().__init__(cam_geom, model_path)

        self.calib_cut_v = calib_cut_v

        # build u,v grid
        uv = []
        for v in range(calib_cut_v, self.cg.image_height):
            for u in range(self.cg.image_width):
                uv.append(np.array([u,v]))
        self.uv_grid = np.array(uv)

        self.estimated_pitch_deg = 0
        self.estimated_yaw_deg = 0
        self.update_cam_geometry()
        self.pitch_yaw_history = []
        self.calibration_success = False

    def run_and_viz(self, image):
        _, left_probs, right_probs = self.detect(image)
        line_left  = self._fit_line_v_of_u(left_probs)
        line_right = self._fit_line_v_of_u(right_probs)
        if (line_left is not None) and (line_right is not None):
            vanishing_point = get_intersection(line_left, line_right)
            if vanishing_point is not None:                
                u_i, v_i = vanishing_point
                pitch, yaw = get_py_from_vp(u_i, v_i, self.cg.intrinsic_matrix)
                self.add_to_pitch_yaw_history(pitch, yaw)

        left_poly = self.fit_poly(left_probs)
        right_poly = self.fit_poly(right_probs)
        return left_poly, right_poly, left_probs, right_probs


    def __call__(self, image):
        if isinstance(image, str):
            image = self.read_imagefile_to_array(image)
        left_poly, right_poly, _, _ = self.run_and_viz(image)
        return left_poly, right_poly

    
    def _fit_line_v_of_u(self, probs):
        probs_flat = np.ravel(probs[self.calib_cut_v:, :])
        mask = probs_flat > 0.3
        if mask.sum() == 0:
            return None
        coeffs, residuals, _, _, _ = np.polyfit(
            self.uv_grid[:,0][mask], self.uv_grid[:,1][mask], deg=1, w=probs_flat[mask], full=True)
        mean_residuals = residuals/len(self.uv_grid[:,0][mask])
        #print(mean_residuals)
        if mean_residuals > 15:
            return None
        else:
            return np.poly1d(coeffs)

    def add_to_pitch_yaw_history(self, pitch, yaw):
        self.pitch_yaw_history.append([pitch, yaw])
        if len(self.pitch_yaw_history) > 50:
            py = np.array(self.pitch_yaw_history)
            mean_pitch = np.mean(py[:,0])
            mean_yaw = np.mean(py[:,1])
            self.estimated_pitch_deg = np.rad2deg(mean_pitch)
            self.estimated_yaw_deg = np.rad2deg(mean_yaw)
            self.update_cam_geometry()
            self.calibration_success = True
            self.pitch_yaw_history = []
            print("yaw, pitch = ", self.estimated_yaw_deg, self.estimated_pitch_deg)

    def update_cam_geometry(self):
        self.cg = CameraGeometry(
            height = self.cg.height, 
            roll_deg = self.cg.roll_deg,
            image_width = self.cg.image_width,
            image_height = self.cg.image_height, 
            field_of_view_deg = self.cg.field_of_view_deg,
            pitch_deg = self.estimated_pitch_deg, 
            yaw_deg = self.estimated_yaw_deg )
        self.cut_v, self.grid = self.cg.precompute_grid()

