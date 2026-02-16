#!/usr/bin/env python3
# -*- coding: utf-8 -*-
__author__ = 'Antoine Weill--Duflos'
__version__ = '1.0.0'
__date__ = '2021/03/22'
__description__ = 'Python Pantograph mech. definitions'

from pyhapi import Mechanisms
import math

class Pantograph(Mechanisms):
    __l = __L = __d = 0
    __th1 = __th2 = 0
    __tau1 = __tau2 = 0
    __f_x = __f_y = 0
    __q_x = __q_y = 0
    __x_E = __y_E = 0
    __pi = math.pi
    __J11 = __J12 = __J21 = __J22 = 0
    __gain = 1

    def __init__(self):
        self.__l = 0.07
        self.__L = 0.09
        self.__d = 0.038
    

    def mgd(self, q1, q2):

        c1 = math.cos(q1)
        c2 = math.cos(q2)
        s1 = math.sin(q1)
        s2 = math.sin(q2)

        # position du point A : extremite de la bielle 1 
        xA = -self.__d/2 + self.__l * c1
        yA = self.__l * s1
        
        # position du point B : extremite de la bielle 2
        xB = self.__d/2 + self.__l * c2
        yB = self.__l * s2
        
        # distance entre les points A et B
        D = math.sqrt( math.pow((xA-xB),2) + math.pow((yA-yB),2) )
        
        # angle entre l'axe X et le vecteur BA
        gamma = math.atan2( yA-yB, xA-xB )
        
        # angle entre le vecteur BP et le vecteur BA
        # on se positionne dans le triangle ABP et on applique le theoreme de Pythagore generalise :
        # ||AP||² = ||BP||² + ||AB||² + 2*||BP||*||AB||*cos(<BP,BA>)
        # applique a notre cas (||AP||=||BP||=L) : <BP,BA> = acos(D²/2*L*D)
        delta = abs( math.acos( math.pow(D,2)/(2*self.__L*D) ) )
        
        # position de l'effecteur
        x_P = xB + self.__L*math.cos(gamma-delta)
        y_P = yB + self.__L*math.sin(gamma-delta)

        return x_P, y_P              


    # q1, q2, dq en [rad]
    def jacobian(self, q1, q2, dq):

        x_p, y_p = self.mgd(q1, q2)
        x_p1, y_p1 = self.mgd(q1+dq, q2)    # variation de q1
        x_p2, y_p2 = self.mgd(q1, q2+dq)    # variation de q2

        # on calcule la jacobienne numeriquement
        J11 = (x_p1-x_p)/dq
        J21 = (y_p1-y_p)/dq
        J12 = (x_p2-x_p)/dq
        J22 = (y_p2-y_p)/dq

        return J11, J21, J12, J22


    def forwardKinematics(self, angles):

        self.__th1 = self.__pi / 180 * angles[0]
        self.__th2 = self.__pi / 180 * angles[1]

        # on recalcule les angles pour etre dans la configuration utilisee lors du modele
        th1 = self.__pi / 180 * (angles[0]+90)
        th2 = self.__pi / 180 * (90-angles[1])

        self.__x_E, self.__y_E = self.mgd(th1, th2)
        self.__J11, self.__J21, self.__J12, self.__J22 = self.jacobian(th1, th2, 2*self.__pi/100)
        
            
    def torqueCalculation(self, force):
        
        fx = force[0]
        fy = force[1]
        
        # on calcule les couples a transmettre, calcules dans le repere utilise pour le calcul du repere geomatrique direct et de la matrice jacobienne
        tau1 = self.__J11*fx + self.__J21*fy
        tau2 = self.__J12*fx + self.__J22*fy
        
        # on retranscrit dans le repere des moteurs (l'articulation 2 est inversee)
        tau2 = -tau2
        
        # on applique des gains
        tau1 *= self.__gain
        tau2 *= self.__gain
        
        # valeurs des attributs
        self.__fx = fx
        self.__fy = fy
        
        self.__tau1 = tau1
        self.__tau2 = tau2
        


    def op_velocityCalculation(self, q):
        op_vels = [0.0,0.0]
        self.__q_x = q[0]
        self.__q_y = q[1]

        op_vels[0] = self.__J11*self.__q_x + self.__J21*self.__q_y
        op_vels[1] = self.__J12*self.__q_x + self.__J22*self.__q_y

        op_vels[0]*= self.__gain
        op_vels[1]*= self.__gain

        return op_vels

    def forceCalculation(self):
        pass

    def positionControl(self):
        pass

    def inverseKinematics(self):
        pass
    
    def set_mechanism_parameters(self, parameters):
        self.__l = parameters[0]
        self.__L = parameters[1]
        self.__d = parameters[2]

    def set_sensor_data(self, data):
        pass

    def get_coordinate(self):
        return [self.__x_E, self.__y_E]
    
    def get_torque(self):
        return [self.__tau1, self.__tau2]

    def get_angle(self):
        return [self.__th1, self.__th2]