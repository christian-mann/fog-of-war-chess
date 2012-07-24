from math import pi, sin, cos

from direct.showbase.ShowBase import ShowBase
from direct.task import Task
from direct.actor import Actor
from direct.interval.IntervalGlobal import Sequence
from panda3d.core import *

class MyApp(ShowBase):
	def __init__(self):
		ShowBase.__init__(self)
		
		self.environ = self.loader.loadModel("models/environment")
		self.environ.reparentTo(self.render)
		
		self.environ.setScale(0.25, 0.25, 0.25)
		self.environ.setPos(-8, 42, 0)
		
		#self.taskMgr.add(self.spinCameraTask, "SpinCameraTask")
		
		self.pandaActor = Actor.Actor("models/panda-model", {"walk": "models/panda-walk4"})
		self.pandaActor.setScale(0.005, 0.005, 0.005)
		self.pandaActor.reparentTo(self.render)
		self.pandaActor.loop("walk")
		
		
		
		i1 = self.pandaActor.posInterval(13, Point3(0, -10, 0), startPos=Point3(0,10,0))
		i2 = self.pandaActor.posInterval(13, Point3(0, 10, 0))
		i3 = self.pandaActor.hprInterval( 3, Point3(180, 0, 0))
		i4 = self.pandaActor.hprInterval( 3, Point3(0, 0, 0))
		self.pandaPace = Sequence(i1,i3,i2,i4)
		self.pandaPace.loop()
		
		
		render.setLightOff()
		
		
		slight = Spotlight('slight')
		slight.setColor(Vec4(1,1,1,1))
		lens = PerspectiveLens()
		slight.setLens(lens)
		slight.setShadowCaster(True)
		slnp = self.pandaActor.attachNewNode(slight)
		slnp.setPos(0,0,10)
		slnp.lookAt(self.pandaActor)
		render.setLight(slnp)
		
		render.setShaderAuto()
		
	def spinCameraTask(self, task):
		angleDegrees = task.time * 6.0
		angleRadians = angleDegrees * pi / 180.0
		self.camera.setPos(10.0 * sin(angleRadians), -20.0 * cos(angleRadians), 3)
		self.camera.setHpr(angleDegrees, 0, 0)
		return Task.cont
	
app = MyApp()
app.run()