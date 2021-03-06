# EKF SLAM - prediction, landmark assignment and correction.
#
# slam_09_c_slam_correction
# Claus Brenner, 20 JAN 13
from lego_robot import *
from math import sin, cos, pi, atan2, sqrt
import numpy as np
from slam_f_library import get_observations, write_cylinders,\
     write_error_ellipses

def dist(p, q):
    dis = sqrt((p[1]-(q[1]))**2 + (p[0]-q[0])**2)
    return dis
dist([1,1],[2,2])
class ExtendedKalmanFilterSLAM:
    def __init__(self, state, covariance,
                 robot_width, scanner_displacement,
                 control_motion_factor, control_turn_factor,
                 measurement_distance_stddev, measurement_angle_stddev):
        # The state. This is the core data of the Kalman filter.
        self.state = state
        self.covariance = covariance

        # Some constants.
        self.robot_width = robot_width
        self.scanner_displacement = scanner_displacement
        self.control_motion_factor = control_motion_factor
        self.control_turn_factor = control_turn_factor
        self.measurement_distance_stddev = measurement_distance_stddev
        self.measurement_angle_stddev = measurement_angle_stddev

        # Currently, the number of landmarks is zero.
        self.number_of_landmarks = 0
    @staticmethod
    def g(state, control, w):
        x, y, theta = state
        l, r = control
        if r != l:
            alpha = (r - l) / w
            rad = l/alpha
            g1 = x + (rad + w/2.)*(sin(theta+alpha) - sin(theta))
            g2 = y + (rad + w/2.)*(-cos(theta+alpha) + cos(theta))
            g3 = (theta + alpha + pi) % (2*pi) - pi
        else:
            g1 = x + l * cos(theta)
            g2 = y + l * sin(theta)
            g3 = theta

        return np.array([g1, g2, g3])

    @staticmethod
    def dg_dstate(state, control, w):
        theta = state[2]
        l, r = control
        if r != l:
            alpha = (r-l)/w
            theta_ = theta + alpha
            rpw2 = l/alpha + w/2.0
            m = np.array([[1.0, 0.0, rpw2*(cos(theta_) - cos(theta))],
                       [0.0, 1.0, rpw2*(sin(theta_) - sin(theta))],
                       [0.0, 0.0, 1.0]])
        else:
            m = np.array([[1.0, 0.0, -l*sin(theta)],
                       [0.0, 1.0,  l*cos(theta)],
                       [0.0, 0.0,  1.0]])
        return m

    @staticmethod
    def dg_dcontrol(state, control, w):
        theta = state[2]
        l, r = tuple(control)
        if r != l:
            rml = r - l
            rml2 = rml * rml
            theta_ = theta + rml/w
            dg1dl = w*r/rml2*(sin(theta_)-sin(theta))  - (r+l)/(2*rml)*cos(theta_)
            dg2dl = w*r/rml2*(-cos(theta_)+cos(theta)) - (r+l)/(2*rml)*sin(theta_)
            dg1dr = (-w*l)/rml2*(sin(theta_)-sin(theta)) + (r+l)/(2*rml)*cos(theta_)
            dg2dr = (-w*l)/rml2*(-cos(theta_)+cos(theta)) + (r+l)/(2*rml)*sin(theta_)
            
        else:
            dg1dl = 0.5*(cos(theta) + l/w*sin(theta))
            dg2dl = 0.5*(sin(theta) - l/w*cos(theta))
            dg1dr = 0.5*(-l/w*sin(theta) + cos(theta))
            dg2dr = 0.5*(l/w*cos(theta) + sin(theta))

        dg3dl = -1.0/w
        dg3dr = 1.0/w
        m = np.array([[dg1dl, dg1dr], [dg2dl, dg2dr], [dg3dl, dg3dr]])
            
        return m

    def predict(self, control):
        """The prediction step of the Kalman filter."""
        # covariance' = G * covariance * GT + R
        # where R = V * (covariance in control space) * VT.
        # Covariance in control space depends on move distance.
        G3 = self.dg_dstate(self.state, control, self.robot_width)
        left, right = control
        left_var = (self.control_motion_factor * left)**2 +\
                   (self.control_turn_factor * (left-right))**2
        right_var = (self.control_motion_factor * right)**2 +\
                    (self.control_turn_factor * (left-right))**2
        control_covariance = np.diag([left_var, right_var])
        V = self.dg_dcontrol(self.state, control, self.robot_width)
        R3 = np.dot(V, np.dot(control_covariance, V.T))

        N = self.number_of_landmarks
        N2 = N * 2
        G = np.zeros((3 + N2, 3 + N2))
        G[0:3, 0:3] = G3
        G[3:, 3:] = np.eye(N2)

        R = np.zeros((3 + N2, 3 + N2))
        R[0:3, 0:3] = R3

        self.covariance = np.dot(G, np.dot(self.covariance, G.T)) + R
        new_state = self.g(self.state[:3, ], control, self.robot_width)
        self.state = np.hstack((new_state[:, ], self.state[3:]))
        # new_state1 = self.g(self.state[:3, ], control, self.robot_width)
        # new_state = (self.state[0:3] + new_state1)/2
        # G3_2 = self.dg_dstate(new_state, control, self.robot_width)
        # V_2 = self.dg_dcontrol(new_state, control, self.robot_width)
        # R3_2 = dot(V_2, dot(control_covariance, V_2.T))
        # G_2 = zeros((3 + N2, 3 + N2))
        # G_2[0:3, 0:3] = G3_2
        # G_2[3:, 3:] = eye(N2)
        # R_2 = zeros((3 + N2, 3 + N2))
        # R_2[0:3, 0:3] = R3_2
        # self.covariance = dot(G_2, dot(self.covariance, G_2.T)) + R_2
        # self.state = hstack((new_state1, self.state[3:]))

    def add_landmark_to_state(self, initial_coords):
        """Enlarge the current state and covariance matrix to include one more
           landmark, which is given by its initial_coords (an (x, y) tuple).
           Returns the index of the newly added landmark."""
        
        # --->>> Put here your previous code to augment the robot's state and
        #        covariance matrix.
        index = self.number_of_landmarks
        self.number_of_landmarks += 1
        x1, y1 = initial_coords
        new_landmark = np.array([x1, y1])
        dim_x, dim_y = self.covariance.shape
        new_matrix = np.zeros((dim_x + 2, dim_y + 2))
        new_matrix[0:dim_x, 0:dim_y] = self.covariance
        new_matrix[dim_x:, dim_y:] = np.diag([10 ** 10, 10 ** 10])
        self.covariance = new_matrix
        new_state = np.hstack((self.state[:, ], new_landmark[:, ]))
        self.state = new_state
        return index

    @staticmethod
    def h(state, landmark, scanner_displacement):
        """Takes a (x, y, theta) state and a (x, y) landmark, and returns the
           measurement (range, bearing)."""
        dx = landmark[0] - (state[0] + scanner_displacement * cos(state[2]))
        dy = landmark[1] - (state[1] + scanner_displacement * sin(state[2]))
        r = sqrt(dx * dx + dy * dy)
        alpha = (atan2(dy, dx) - state[2] + pi) % (2*pi) - pi

        return np.array([r, alpha])

    @staticmethod
    def dh_dstate(state, landmark, scanner_displacement):
        theta = state[2]
        cost, sint = cos(theta), sin(theta)
        dx = landmark[0] - (state[0] + scanner_displacement * cost)
        dy = landmark[1] - (state[1] + scanner_displacement * sint)
        q = dx * dx + dy * dy
        sqrtq = sqrt(q)
        drdx = -dx / sqrtq
        drdy = -dy / sqrtq
        drdtheta = (dx * sint - dy * cost) * scanner_displacement / sqrtq
        dalphadx =  dy / q
        dalphady = -dx / q
        dalphadtheta = -1 - scanner_displacement / q * (dx * cost + dy * sint)

        return np.array([[drdx, drdy, drdtheta],
                      [dalphadx, dalphady, dalphadtheta]])
        # Actually we only use the first 3 elements of state.

    def correct(self, measurement, landmark_index):
        """The correction step of the Kalman filter."""
        # Get (x_m, y_m) of the landmark from the state vector.
        landmark = self.state[3+2*landmark_index : 3+2*landmark_index+2]
        H3 = self.dh_dstate(self.state, landmark, self.scanner_displacement)
        # Actually we only use the first 3 elements of state.

        # --->>> Add your code here to set up the full H matrix.
        N = self.number_of_landmarks
        new_H = np.zeros((2, 3+2*N))
        new_H[:, 0:3] = H3
        new_H[:, 3+2*landmark_index:3+2*landmark_index+2] = H3[:, 0:2] * (-1)

        H = new_H  # Replace this.

        # This is the old code from the EKF - no modification necessary!
        Q = np.diag([self.measurement_distance_stddev**2,
                  self.measurement_angle_stddev**2])
        K = np.dot(self.covariance,
                np.dot(H.T, np.linalg.inv(np.dot(H, np.dot(self.covariance, H.T)) + Q)))
        innovation = np.array(measurement) -\
                     self.h(self.state, landmark, self.scanner_displacement)
        innovation[1] = (innovation[1] + pi) % (2*pi) - pi
        self.state = self.state + np.dot(K, innovation)
        self.covariance = np.dot(np.eye(np.size(self.state)) - np.dot(K, H),
                              self.covariance)

    def get_landmarks(self):
        """Returns a list of (x, y) tuples of all landmark positions."""
        return ([(self.state[3+2*j], self.state[3+2*j+1])
                 for j in xrange(self.number_of_landmarks)])

    def get_landmark_error_ellipses(self):
        """Returns a list of all error ellipses, one for each landmark."""
        ellipses = []
        for i in xrange(self.number_of_landmarks):
            j = 3 + 2 * i
            ellipses.append(self.get_error_ellipse(
                self.covariance[j:j+2, j:j+2]))
        return ellipses

    @staticmethod
    def get_error_ellipse(covariance):
        """Return the position covariance (which is the upper 2x2 submatrix)
           as a triple: (main_axis_angle, stddev_1, stddev_2), where
           main_axis_angle is the angle (pointing direction) of the main axis,
           along which the standard deviation is stddev_1, and stddev_2 is the
           standard deviation along the other (orthogonal) axis."""
        eigenvals, eigenvects = np.linalg.eig(covariance[0:2,0:2])
        angle = atan2(eigenvects[1,0], eigenvects[0,0])
        return (angle, sqrt(eigenvals[0]), sqrt(eigenvals[1]))

    @staticmethod
    def compute_center(point_list):
        # Safeguard against empty list.
        if not point_list:
            return (0.0, 0.0)
        # If not empty, sum up and divide.
        sx = sum([p[0] for p in point_list])
        sy = sum([p[1] for p in point_list])
        return (sx / len(point_list), sy / len(point_list))

    @staticmethod
    def estimate_transform(left_list, right_list, fix_scale=False):
        if len(left_list) < 3 or len(right_list) < 3:  # at least two points
            return None
        # Compute left and right center.
        lc = ExtendedKalmanFilterSLAM.compute_center(left_list)
        rc = ExtendedKalmanFilterSLAM.compute_center(left_list)
        l_i = [tuple(np.subtract(l, lc)) for l in
               left_list]  # tuple subtract tuple, not only x but also y, l_i is a list
        r_i = [tuple(np.subtract(r, rc)) for r in right_list]
        cs, ss, rr, ll = 0.0, 0.0, 0.0, 0.0
        for i in range(len(left_list)):
            cs += r_i[i][0] * r_i[i][0] + r_i[i][1] * r_i[i][1]
            ss += -(r_i[i][0] * l_i[i][1]) + r_i[i][1] * l_i[i][0]
            rr += (r_i[i][0] * r_i[i][0]) + (r_i[i][1] * r_i[i][1])
            ll += (l_i[i][0] * l_i[i][0]) + (l_i[i][1] * l_i[i][1])

        if rr == 0.0 or ll == 0.0:
            return None
        if fix_scale:
            la = 1.0
        else:
            la = sqrt(rr / ll)

        if cs == 0.0 or ss == 0.0:
            return None
        else:
            c = cs / sqrt(cs * cs + ss * ss)
            s = ss / sqrt(cs * cs + ss * ss)

        tx = rc[0] - la * (c * lc[0] - s * lc[1])
        ty = rc[1] - (la * ((s * lc[0]) + (c * lc[1])))

        return la, c, s, tx, ty

    @staticmethod
    def apply_transform(trafo, p):
        la, c, s, tx, ty = trafo
        lac = la * c
        las = la * s
        #print p
        x = lac * p[0] - las * p[1] + tx
        y = las * p[0] + lac * p[1] + ty
        #print (x, y)
        return (x, y)

    def correct_pose(self, trafo):
        la, c, s, tx, ty = trafo
        x, y = ExtendedKalmanFilterSLAM.apply_transform(trafo, (self.state[0], self.state[1]))
        theta = self.state[2] + atan2(s, c)
        self.state[0:3] = [x, y, theta]

if __name__ == '__main__':
    # Robot constants.
    scanner_displacement = 30.0
    ticks_to_mm = 0.349
    robot_width = 155.0

    # Cylinder extraction and matching constants.
    minimum_valid_distance = 20.0
    depth_jump = 100.0
    cylinder_offset = 90.0
    max_cylinder_distance = 500.0

    # Filter constants.
    control_motion_factor = 0.35  # Error in motor control.
    control_turn_factor = 0.6  # Additional error due to slip when turning.
    measurement_distance_stddev = 600.0  # Distance measurement error of cylinders.
    measurement_angle_stddev = 45. / 180.0 * pi  # Angle measurement error.

    # Arbitrary start position.
    # initial_state = array([500.0, 0.0, 45.0 / 180.0 * pi])
    initial_state =np.array([1850.0, 1897.0, 3.717551306747922])
    # Covariance at start position.
    initial_covariance = np.zeros((3,3))
    count = 0
    # Setup filter.
    kf = ExtendedKalmanFilterSLAM(initial_state, initial_covariance,
                                  robot_width, scanner_displacement,
                                  control_motion_factor, control_turn_factor,
                                  measurement_distance_stddev,
                                  measurement_angle_stddev)

    # Read data.
    logfile = LegoLogfile()
    logfile.read("robot4_motors.txt")
    logfile.read("robot4_scan.txt")

    # Loop over all motor tick records and all measurements and generate
    # filtered positions and covariances.
    # This is the EKF SLAM loop.
    f = open("ekf_slam_correction.txt", "w")
    m = open("modify.txt","w")
    #k = open("pure.txt","w")
    # likely_step = []

    for i in xrange(len(logfile.motor_ticks)):
        # Prediction.
        control = np.array(logfile.motor_ticks[i]) * ticks_to_mm
        kf.predict(control)
        # Correction.
        observations = get_observations(
            logfile.scan_data[i],
            depth_jump, minimum_valid_distance, cylinder_offset,
            kf, max_cylinder_distance)

        left = []
        right = []
        trafo = []
        # if abs(logfile.motor_ticks[i][1] - logfile.motor_ticks[i][0]) > 30 :
        #      count += 1
        # if count > 3:
        # if abs(logfile.motor_ticks[i][1] - logfile.motor_ticks[i][0]) > 100:
        for obs in observations:
            measurement, cylinder_world, cylinder_scanner, cylinder_index = obs
            if cylinder_index != -1:
                #dis = dist(cylinder_world, kf.state[3 + 2 * cylinder_index:3 + 2 * cylinder_index + 2])
                #print dis
                dis1 = abs(cylinder_world[0] - kf.state[3 + 2 * cylinder_index])
                dis2 = abs(cylinder_world[1] - kf.state[4 + 2 * cylinder_index])
                #if dis < 58:
                if dis1 < 30 and dis2 < 30:
                    left.append(cylinder_world)
                    right.append(kf.state[3 + 2 * cylinder_index:3 + 2 * cylinder_index + 2])
                    #print dis
        trafo = ExtendedKalmanFilterSLAM.estimate_transform(left, right, fix_scale=True)
        print i
        print left
        print right
        print trafo
        if trafo:
            # print kf.state[1:4]
            kf.correct_pose(trafo)
            # print left
            # print right
            # print i
            # print len(left)
            # print left
            # print right
            #print trafo
            # print kf.state[1:4]
            # count = 0
            # print trafo


        # The detected and corresponded cylinder information tuple.
        for obs in observations:
            measurement, cylinder_world, cylinder_scanner, cylinder_index = obs
            # The detected cylinder in forms of tuple (rays index, length), coordinates in the word and
            # coordinates in the robot and the corresponded cylinder's index.
            if cylinder_index == -1:    # If observed for the first time.
                 cylinder_index = kf.add_landmark_to_state(cylinder_world)
        # Put in the world coordinates, return the new assigned index.
            kf.correct(measurement, cylinder_index)
        # left = []
        # right = []
        # trafo = []
        # # if abs(logfile.motor_ticks[i][1] - logfile.motor_ticks[i][0]) > 30 :
        # #      count += 1
        # # if count > 3:
        # # if abs(logfile.motor_ticks[i][1] - logfile.motor_ticks[i][0]) > 100:
        # for obs in observations:
        #     measurement, cylinder_world, cylinder_scanner, cylinder_index = obs
        #     if cylinder_index != -1:
        #         dis = dist(cylinder_world, kf.state[3 + 2 * cylinder_index:3 + 2 * cylinder_index + 2])
        #         if dis < 70:
        #             left.append(cylinder_world)
        #             right.append(kf.state[3 + 2 * cylinder_index:3 + 2 * cylinder_index + 2])
        #             print dis
        # if len(left) > 2:
        #     trafo = ExtendedKalmanFilterSLAM.estimate_transform(left, right, fix_scale=True)
        #
        # if trafo:
        #     # print kf.state[1:4]
        #     kf.correct_pose(trafo)
        #     # print left
        #     # print right
        #     print trafo
        #     # print kf.state[1:4]
        #     # count = 0
        #     # print trafo
        # like = []
        # for i in xrange(kf.number_of_landmarks):
        #     reference = array(((1291.0,1881.0),(383.0,1458.0),(482.0,682.0),(1191.0,747.0),(1693.0,1043.0),(1805.0,190.0)))
        #     co = kf.covariance[3+2*i:5+2*i, 3+2*i:5+2*i]
        #     det = linalg.det(co)
        #     delta = reference[i] - kf.state[3+2*i:5+2*i,]
        #     e_factor = -0.5 * dot(dot(delta.T, linalg.inv(co)), delta)
        #     l = exp(e_factor) / (2 * pi * sqrt(det))
        #     like.append(l)
        # likely_step.append(like)

        # End of EKF SLAM - from here on, data is written.

        # Output the center of the scanner, not the center of the robot.
        print >> f, "F %f %f %f" % \
            tuple(kf.state[0:3] + [scanner_displacement * cos(kf.state[2]),
                                   scanner_displacement * sin(kf.state[2]),
                                   0.0])
        print >> m, "F %f %f %f" % \
                    tuple(kf.state[0:3] + [scanner_displacement * cos(kf.state[2]),
                                           scanner_displacement * sin(kf.state[2]),
                                           0.0])
        # print >> k, "K %f %f %f" % \
        #             tuple(kf.state[0:3] + [scanner_displacement * cos(kf.state[2]),
        #                                    scanner_displacement * sin(kf.state[2]),
        #                                    0.0])
        # Write covariance matrix in angle stddev1 stddev2 stddev-heading form.
        e = ExtendedKalmanFilterSLAM.get_error_ellipse(kf.covariance)
        print >> f, "E %f %f %f %f" % (e + (sqrt(kf.covariance[2,2]),))
        # Write estimates of landmarks.
        write_cylinders(f, "W C", kf.get_landmarks())
        # Write error ellipses of landmarks.
        write_error_ellipses(f, "W E", kf.get_landmark_error_ellipses())
        # Write cylinders detected by the scanner.
        write_cylinders(f, "D C", [(obs[2][0], obs[2][1])
                                   for obs in observations])

    # likely_step_a = np.array(likely_step)
    # plt.figure()
    # for i in range(0, 6):
    #     plt.plot(likely_step_a[:, i], label="det_cylinder_%d" % i, lw=2)
    # plt.xlabel("Steps")
    # plt.ylabel("likely")
    # plt.xlim(0,)
    # plt.ylim(0,0.000035)
    # plt.title("Probability Density at ref point")
    # plt.legend()
    # plt.grid(True, linestyle="--", lw=1)
    # plt.show()

    f.close()
