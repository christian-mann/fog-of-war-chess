# Author: Christian Mann
# Credits: Shao Zhang, Phil Saltzman for providing the models and chessboard base for grabbing and dropping pieces
# Last updated: 5/5/2012

import direct.directbase.DirectStart
from panda3d.core import CollisionTraverser,CollisionNode
from panda3d.core import CollisionHandlerQueue,CollisionRay
from panda3d.core import AmbientLight,DirectionalLight,LightAttrib,Spotlight,PerspectiveLens
from panda3d.core import TextNode
from panda3d.core import *
from pandac.PandaModules import *
from direct.gui.OnscreenText import OnscreenText
from direct.showbase.DirectObject import DirectObject
from direct.task.Task import Task
from direct.interval.IntervalGlobal import Sequence,Parallel,Func
from direct.distributed.PyDatagram import PyDatagram
from direct.distributed.PyDatagramIterator import PyDatagramIterator
from direct.gui.OnscreenText import OnscreenText 
from direct.gui.DirectGui import *

import random
from fractions import gcd
import sys
from collections import defaultdict

#color constants
BLACK = (0,0,0,1)
WHITE = (1,1,1,1)
HIGHLIGHT = (0,1,1,1)
PIECEBLACK = (.15, .15, .15, 1)
PIECEWHITE = WHITE

SERVER = "Server"
CLIENT = "Client"

#flips server <-> client and black <-> white
flip = {PIECEBLACK: PIECEWHITE, PIECEWHITE: PIECEBLACK, SERVER: CLIENT, CLIENT: SERVER}

#intersection of a line and a plane
def PointAtZ(z, point, vec):
	return point + vec * ((z - point.getZ()) / vec.getZ())

#position of each chessboard square in space
def SquarePos((x,y)):
	return ((x - 3.5, y - 3.5, 0))

#determines whether a square is white or black
def SquareColor((x,y)):
	if (x + y)%2: return BLACK
	else: return WHITE
	
class World(DirectObject):
	def __init__(self, mode, ip=None):
		
		if mode==CLIENT and not ip:
			#Don't let this happen.
			print "WTF programmer"
			sys.exit()
		
		#current dialog box
		self.d = None
		
		#top-left of screen; contains instructions on how to exit the game.
		self.quitInstructions = OnscreenText(text='Press ESC to exit.', pos=(-1, 0.95), scale=0.05, fg=(1,1,1,1), bg=(0,0,0,0), mayChange=False)
		
		#bottom of screen
		self.turnIndicator = OnscreenText(text='', pos=(0,-0.8), scale=0.1, fg=(1,1,1,1), bg=(0,0,0,0), mayChange=True)
		
		#Saving some values, some default values
		self.mode = mode
		self.player = {SERVER: PIECEWHITE, CLIENT: PIECEBLACK}[self.mode]
		self.ip = ip
		
		#Panda3D, by default, allows for camera control with the mouse.
		base.disableMouse()
		
		self.setupMouse()
		self.setupBoard()
		self.setupCamera()
		self.setupPieces()
		self.setupNetwork()
		self.setupLights()
		
		#some internal state for making clicky moves
		self.hiSq = None
		self.dragOrigin = None
		
		#keyboard, mouse
		self.mouseTask = taskMgr.add(self.tskMouse, 'mouseTask')
		self.accept('mouse1', self.handleClick)
		self.accept('f2', lambda: base.setFrameRateMeter(True))
		self.accept('f3', lambda: base.setFrameRateMeter(False))
		self.accept('escape', sys.exit)
		
		
		#first turn
		self.turn = PIECEWHITE
	
	#### INITIALIZATION ####
	
	def setupBoard(self):
		#We will attach all of the squares to their own root. This way we can do the
		#collision pass just on the sqaures and save the time of checking the rest
		#of the scene
		self.squareRoot = render.attachNewNode("squareRoot")

		#For each square
		self.squares = dict(((i,j), None) for i in range(8) for j in range(8))
		for place in self.squares:
			#Load, parent, color, and position the model (a single square polygon)
			self.squares[place] = loader.loadModel("models/square")
			self.squares[place].reparentTo(self.squareRoot)
			self.squares[place].setPos(SquarePos(place))
			self.squares[place].setColor(SquareColor(place))
			#Set the model itself to be collideable with the ray. If this model was
			#any more complex than a single polygon, you should set up a collision
			#sphere around it instead. But for single polygons this works fine.
			self.squares[place].find("**/polygon").node().setIntoCollideMask(
			  BitMask32.bit(1))
			#Set a tag on the square's node so we can look up what square this is
			#later during the collision pass
			self.squares[place].find("**/polygon").node().setTag('square', ' '.join(map(str,place)))

	def setupPieces(self):
		#Default dictionaries work decently well as an easy two-dimensional array.
		self.pieces = defaultdict(lambda: None)
		
		#The order of pieces on a chessboard from white's perspective
		pieceOrder = [Rook, Knight, Bishop, Queen, King, Bishop, Knight, Rook]
		
		for i in xrange(8):
			#load white pawns
			self.pieces[i, 1] = Pawn((i,1), PIECEWHITE)
			
			#load black pawns
			self.pieces[i, 6] = Pawn((i, 6), PIECEBLACK)
			
			#load white specials
			self.pieces[i, 0] = pieceOrder[i]((i,0), PIECEWHITE)
			
			#load black specials
			self.pieces[i, 7] = pieceOrder[i]((i,7), PIECEBLACK)
	
	# TODO: Notice when the other side disconnects
	def setupNetwork(self):
		if self.mode == CLIENT:
			self.setupClient(self.ip)
		else:
			self.setupServer()
	
	# A lot of the below two methods is boilerplate straight from Panda3D documentation.
	def setupServer(self):
		self.cManager = QueuedConnectionManager()
		self.cListener = QueuedConnectionListener(self.cManager, 0)
		self.cReader = QueuedConnectionReader(self.cManager, 0)
		self.cWriter = ConnectionWriter(self.cManager,0)
		
		self.oppConnection = None
		port = 15905 # Chosen by fair dice roll.
		             # Guaranteed to be random.
		backlog = 1000
		tcpSocket = self.cManager.openTCPServerRendezvous(port, backlog)
		
		self.cListener.addConnection(tcpSocket)
		
		def tskListenerPoll(task):
			if self.cListener.newConnectionAvailable() and not self.oppConnection:
				rendezvous = PointerToConnection()
				addr = NetAddress()
				newCon = PointerToConnection()
				
				if self.cListener.getNewConnection(rendezvous, addr, newCon):
					newConnection = newCon.p()
					print "Received connection from %s" % newConnection.getAddress()
					self.oppConnection = newConnection
					self.cReader.addConnection(newConnection)
					
					#server starts the game
					self.turnIndicator['text'] = 'Your turn!'
					self.showVisibleSquares()
					
					#remove the dialog node from below
					if self.d: self.d.removeNode()
					
					return Task.done
			if not self.d: self.d = DirectDialog(text="Waiting for client to connect...", buttonTextList=[], buttonValueList=[])
			return Task.cont
			
		taskMgr.add(tskListenerPoll, "Poll the connection listener")
		taskMgr.add(self.tskReaderPoll, "Poll the connection reader")
	
	def setupClient(self, ip):
		self.cManager = QueuedConnectionManager()
		self.cReader = QueuedConnectionReader(self.cManager, 0)
		self.cWriter = ConnectionWriter(self.cManager,0)
		
		self.oppConnection = None
		
		port = 15905
		timeout = 3000
		myConnection = self.cManager.openTCPClientConnection(ip, port, timeout)
		if myConnection:
			self.cReader.addConnection(myConnection)
			self.oppConnection = myConnection
			
			taskMgr.add(self.tskReaderPoll, "Poll the connection reader")
			self.showVisibleSquares()
		else:
			self.d = OkDialog(text="Could not connect to server at '%s'" % ip, command=sys.exit)
	
	# Makes sure player gets a decent view of the game board, and *not* of the hidden pieces below the board. Shhhh...
	def setupCamera(self):
		if self.player == PIECEWHITE:
			camera.setPos(0, -13.75, 8)
			camera.lookAt(self.squareRoot)
			camera.setH(0)
		else:
			camera.setPos(0, 13.75, 8)
			camera.lookAt(self.squareRoot)
			camera.setH(180)
	
	# Adds some ambient lights and a directional light
	def setupLights(self):
		#This is one area I know hardly anything about. I really don't know how to get this to behave nicely.
		#The black pieces are hardly distinguishable.
		ambientLight = AmbientLight( "ambientLight" )
		ambientLight.setColor( Vec4(.8, .8, .8, 1) )
		directionalLight = DirectionalLight( "directionalLight" )
		directionalLight.setDirection( Vec3( 0, 45, -45 ) )
		directionalLight.setColor( Vec4( 0.2, 0.2, 0.2, 1 ) )
		render.setLight(render.attachNewNode( directionalLight ) )
		render.setLight(render.attachNewNode( ambientLight ) )
	
	# Sets up collision detection for the mouse cursor.
	def setupMouse(self):
		#Since we are using collision detection to do picking, we set it up like
		#any other collision detection system with a traverser and a handler
		self.picker = CollisionTraverser()            #Make a traverser
		self.pq     = CollisionHandlerQueue()         #Make a handler
		#Make a collision node for our picker ray
		self.pickerNode = CollisionNode('mouseRay')
		#Attach that node to the camera since the ray will need to be positioned
		#relative to it
		self.pickerNP = camera.attachNewNode(self.pickerNode)
		#Everything to be picked will use bit 1. This way if we were doing other
		#collision we could seperate it
		self.pickerNode.setFromCollideMask(BitMask32.bit(1))
		self.pickerRay = CollisionRay()               #Make our ray
		self.pickerNode.addSolid(self.pickerRay)      #Add it to the collision node
		#Register the ray as something that can cause collisions
		self.picker.addCollider(self.pickerNP, self.pq)
	
	#### TASKS ####
	
	# Checks for incoming data on the connection
	def tskReaderPoll(self, task):
		if self.cReader.dataAvailable():
			datagram = NetDatagram()
			if self.cReader.getData(datagram):
				self.receiveData(datagram)
		return Task.cont
	
	# Runs every frame, checks whether the mouse is highlighting something or another
	def tskMouse(self, task):
		#This task deals with the highlighting and dragging based on the mouse
		
		#First, clear the current highlight
		if self.hiSq:
			self.squares[self.hiSq].setColor(SquareColor(self.hiSq))
			self.hiSq = None
			
		#Check to see if we can access the mouse. We need it to do anything else
		if base.mouseWatcherNode.hasMouse():
			#get the mouse position
			mpos = base.mouseWatcherNode.getMouse()
			
			#Set the position of the ray based on the mouse position
			self.pickerRay.setFromLens(base.camNode, mpos.getX(), mpos.getY())
			
			#If we are dragging something, set the position of the object
			#to be at the appropriate point over the plane of the board
			if self.dragOrigin:
				#camera, relative instead to render
				#Gets the point described by pickerRay.getOrigin(), which is relative to
				nearPoint = render.getRelativePoint(camera, self.pickerRay.getOrigin())
				#Same thing with the direction of the ray
				nearVec = render.getRelativeVector(camera, self.pickerRay.getDirection())
				self.pieces[self.dragOrigin].obj.setPos(
					PointAtZ(.5, nearPoint, nearVec))

			#Do the actual collision pass (Do it only on the squares for
			#efficiency purposes)
			self.picker.traverse(self.squareRoot)
			if self.pq.getNumEntries() > 0:
				#if we have hit something, sort the hits so that the closest
				#is first, and highlight that node
				self.pq.sortEntries()
				p = tuple(map(int, (self.pq.getEntry(0).getIntoNode().getTag('square')).split()))
				
				if self.pieces[p] and self.pieces[p].color == self.turn == self.player and not self.dragOrigin or self.dragOrigin and self.pieces[self.dragOrigin].isValidMove(p, self.pieces):
					#Set the highlight on the picked square
					self.hiSq = p
					self.squares[self.hiSq].setColor(HIGHLIGHT)
			    
		return Task.cont		
	
	def handleClick(self):
		# Disabled when a dialog box is on-screen. Pay attention to what I'm telling you, user!
		if not self.d:
			if self.dragOrigin:
				self.releasePiece()
			else:
				self.grabPiece()
	
	# Comes from handleClick
	def grabPiece(self):
		#If a square is highlighted and it has a piece, set it to dragging mode
		if self.hiSq and self.pieces[self.hiSq] and self.pieces[self.hiSq].color == self.turn:
			self.dragOrigin = self.hiSq
			self.hiSq = None
	
	def releasePiece(self):
		#Letting go of a piece. If we are not on a square, return it to its original
		#position.
		if self.dragOrigin:   #Make sure we really are dragging something
			if self.hiSq and self.hiSq != self.dragOrigin and self.pieces[self.dragOrigin].isValidMove(self.hiSq, self.pieces):
				
				# Verify that this doesn't put the king in check
				# Make backup of the pieces dictionary
				oldPieces = self.pieces.copy()
				
				self.pieces[self.hiSq] = self.pieces[self.dragOrigin]
				self.pieces[self.dragOrigin] = None
				
				if self.inCheck(self.turn):
					self.pieces = oldPieces
					self.pieces[self.dragOrigin].obj.setPos(SquarePos(self.dragOrigin))
					print "Invalid move -- King is in check"
					
					def closeDialog():
						self.d.removeNode()
					self.d = OkDialog(text="That move would put your King in check!", command=closeDialog)
				else:
					self.pieces = oldPieces
					
					self.makeMove(self.dragOrigin, self.hiSq, dt=0, callback=self.showVisibleSquares)
					self.sendMove(self.dragOrigin, self.hiSq)
					self.squares[self.dragOrigin].setColor(SquareColor(self.dragOrigin))
					
					#no longer our turn
					self.turnIndicator['text'] = ''
			else:
				self.pieces[self.dragOrigin].obj.setPos(SquarePos(self.dragOrigin))
				print "Invalid move"
			  
		#We are no longer dragging anything
		self.dragOrigin = False
	
	#### CHESS UPDATES ####
	
	# Moves a piece from one space to another.
	# This should be called to update internal state, whether the piece is already in the correct location or not.
	# Also handles captures.
	def makeMove(self, fr, to, dt=1, callback=None):
		print "Making move %s -> %s" % (str(fr), str(to))
		frP = self.pieces[fr]
		toP = self.pieces[to]
		
		if not frP:
			return False
		if toP and frP.color == toP.color:
			return False
		if not frP.isValidMove(to, self.pieces):
			return False
		
		# Callback function for the movement.
		# Updates pieces' internal state, as well as the true state of the board (self.pieces)
		def updateState():
			self.destroy(toP)
			frP.square = to
			frP.haveMoved = True
			self.pieces[fr] = None
			self.pieces[to] = frP
			self.turn = flip[self.turn]
			
			if self.inCheck(self.player):
				def dismiss(val):
					self.d.removeNode()
				self.d = OkDialog(text="You are in check!", command=dismiss)
			
		s = Sequence(
			frP.obj.posInterval(dt, self.squares[to].getPos()),
			Func(updateState)
		)
		if callback: s.append(Func(callback))
		s.start()
	
	# Removes the piece. This method is passed a Piece object, not a location!
	# Possible improvements: Particle effects! :D
	def destroy(self, piece):
		if piece:
			piece.obj.removeNode()
		
	# Determines whether the player specified by "color" is in check at the current time
	# Future improvements: Calculate the same thing for possible future moves (i.e. if I move here am I therefore in check?)
	def inCheck(self, color):
		#find the king
		kingPlace = [p for p in self.pieces if self.pieces[p] and self.pieces[p].color == color and self.pieces[p].model == "models/king"][0]
		for p in self.pieces:
			if self.pieces[p] and self.pieces[p].color != color and self.pieces[p].isValidMove(kingPlace, self.pieces):
				return True
		return False

	# Currently unused, but could be useful in an (extremely primitive) AI in the future.
	# I ran out of time to put it in this version.
	def makeRandomMove(self):
		move = None
		while not move:
			chosenPiece = random.choice([(x,y) for (x,y) in self.pieces if 0 <= x < 8 and 0 <= y < 8 and self.pieces[x,y] and self.pieces[x,y].color == self.turn])
			if not self.pieces[chosenPiece].validMoves(self.pieces):
				continue
			destSquare = random.choice([s for s in self.pieces[chosenPiece].validMoves(self.pieces)])
			move = (chosenPiece, destSquare)
		self.makeMove(*move)
	
	#### VISIBILITY UPDATES ####
	
	# The next two methods deal with hiding and showing the squares of the board.
	# They hide them by dropping them down below the board.
	def hideSquare(self, sq, dt="default", callback=None):
		
		def internalCallback():
			if self.pieces[sq]: self.pieces[sq].obj.wrtReparentTo(render)
			
		if self.squares[sq] and self.squares[sq].getPos().z == 0:
			if self.pieces[sq]: self.pieces[sq].obj.wrtReparentTo(self.squares[sq])
			dest = self.squares[sq].getPos()
			dest.z = -20
			if dt == "default": dt = abs(dest.z*1.0/20)
			s = Sequence(
				self.squares[sq].posInterval(dt, dest),
				Func(internalCallback)
			)
			if callback: s.append(Func(callback))
			s.start()
			return s
		else:
			if callback: callback()
			return Sequence()
	
	def showSquare(self, sq, dt="default", callback=None):
		
		if self.squares[sq] and self.squares[sq].getPos().z < 0:
		
			dest = self.squares[sq].getPos()
			if dt == "default": dt = abs(dest.z*1.0/20)
			dest.z = 0
			
			def reparent():
				if self.pieces[sq]:
					self.pieces[sq].obj.wrtReparentTo(render)
			
			if self.pieces[sq]: self.pieces[sq].obj.wrtReparentTo(self.squares[sq])
			s = Sequence(
				self.squares[sq].posInterval(dt, dest),
				Func(reparent)
			)
			
			if callback: s.append(Func(callback))
			s.start()
			return s
		else:
			if callback: callback()
			return Sequence()
	
	# Updates the board to show only the squares that are visible at the current time.
	def showVisibleSquares(self, dt="default"):
		visibles = defaultdict(lambda: False)
		for p in [(x,y) for (x,y) in self.pieces if 0 <= x < 8 and 0 <= y < 8]:
			if self.pieces[p]:
				if self.pieces[p].color == self.player:
					for s in self.pieces[p].visibleSquares(self.pieces):
						visibles[s] = True
						
		for s in self.squares:
			if visibles[s]:
				if dt=="default": self.showSquare(s)
				else: self.showSquare(s, dt)
			else:
				if dt=="default": self.hideSquare(s)
				else: self.hideSquare(s, dt)
	
	#### NETWORK I/O ####
	def sendMove(self, fr, to):
		dg = PyDatagram()
		dg.addUint8(fr[0])
		dg.addUint8(fr[1])
		dg.addUint8(to[0])
		dg.addUint8(to[1])
		
		print "Sent move (%d, %d) -> (%d, %d)" % (fr[0], fr[1], to[0], to[1])
		self.cWriter.send(dg, self.oppConnection)
	
	def receiveData(self, dg):
		dg = PyDatagramIterator(dg)
		fr = (dg.getUint8(), dg.getUint8())
		to = (dg.getUint8(), dg.getUint8())
		print "Received move %s -> %s" % (fr, to)
		self.makeMove(fr, to, callback=self.showVisibleSquares)
		
		self.turnIndicator['text'] = 'Your turn!'
		self.sfx = loader.loadSfx('audio/ding.wav')
		self.sfx.play()
	
class Piece:
	def __init__(self, square, color):
		self.obj = loader.loadModel(self.model)
		self.obj.reparentTo(render)
		self.obj.setColor(color)
		self.obj.setPos(SquarePos(square))
		
		self.haveMoved = False
		self.square = square
		self.color = color
		self.dir = 1 if color == PIECEWHITE else -1
	
	def isValidMove(self, dest, pieces):
		return dest in self.validMoves(pieces.copy())
	
	def isValidCapture(self, dest, pieces):
		return self.isValidMove(dest, pieces)
	
	def validMoves(self, pieces):
		return [(i,j) for i in range(8) for j in range(8) if not pieces[i,j] or pieces[i,j].obj.getColor() != self.obj.getColor()]
	
	def visibleSquares(self, pieces):
		return self.validMoves( pieces).union(set([self.square]))
		
	def move(self, dest):
		self.square = dest
		self.haveMoved = True
	
	def path(self, dest):
		startX, startY = self.square
		destX, destY = dest
		
		steps = gcd(abs(destX - startX), abs(destY - startY))
		dx = (destX - startX)/steps
		dy = (destY - startY)/steps
		return [(startX + dx*i, startY + dy*i) for i in xrange(steps+1)]

class Pawn(Piece):
	model = "models/pawn"
	
	def validMoves(self, pieces):
		x,y = self.square
		moves = set()
		if not self.haveMoved:
			if not pieces[x,y+self.dir*2] and not pieces[x, y+self.dir]:
				moves.add((x, y+self.dir*2))
		if not pieces[x, y + self.dir]:
			moves.add((x, y + self.dir))
		
		if pieces[x+1,y+self.dir] and pieces[x+1,y+self.dir].color != self.color:
			moves.add((x+1,y+self.dir))
		if pieces[x-1,y+self.dir] and pieces[x-1,y+self.dir].color != self.color:
			moves.add((x-1,y+self.dir))
		return moves
	
	def visibleSquares(self, pieces):
		#pawns have different visibility rules; namely they can *always* see the three that they could conceivably move to. They're awesome scouts!
		x,y = self.square
		visibles = Piece.visibleSquares(self, pieces)
		visibles.add((x, y+self.dir))
		if x+1<8: visibles.add((x+1, y+self.dir))
		if x-1>=0: visibles.add((x-1, y+self.dir))
		
		return visibles
		
class King(Piece):
	model = "models/king"
	def validMoves(self, pieces):
		x,y = self.square
		return set((i,j) for i in range(8) for j in range(8) if abs(i - x) * abs(j - y) == 1 and (not pieces[i,j] or pieces[i,j].obj.getColor() != self.obj.getColor()))

class Queen(Piece):
	model = "models/queen"
	def validMoves(self, pieces):
		x,y = self.square
		moves = set()
		for i in range(1, (min(8 - x, 8 - y)) + 1):
			if pieces[x+i, y+i]:
				if pieces[x+i, y+i].obj.getColor() != self.obj.getColor():
					moves.add((x+i, y+i))
				break
			else:
				moves.add((x+i, y+i))
		for i in range(1, (min(8 - x, y)) + 1):
			if pieces[x+i, y-i]:
				if pieces[x+i, y-i].obj.getColor() != self.obj.getColor():
					moves.add((x+i, y-i))
				break
			else:
				moves.add((x+i, y-i))
		for i in range(1, (min(x, 8 - y)) + 1):
			if pieces[x-i, y+i]:
				if pieces[x-i, y+i].obj.getColor() != self.obj.getColor():
					moves.add((x-i, y+i))
				break
			else:
				moves.add((x-i, y+i))
		for i in range(1, (min(x, y)) + 1):
			if pieces[x-i, y-i]:
				if pieces[x-i, y-i].obj.getColor() != self.obj.getColor():
					moves.add((x-i, y-i))
				break
			else:
				moves.add((x-i, y-i))
		# +y
		for i in range(1, 8 - y):
			if pieces[x, y+i]:
				if pieces[x, y+i].color != self.color:
					moves.add((x, y+i))
				break
			else:
				moves.add((x, y+i))
		# +x
		for i in range(1, 8 - x):
			if pieces[x+i, y]:
				if pieces[x+i,y].color != self.color:
					moves.add((x+i,y))
				break
			else:
				moves.add((x+i,y))
		
		# -y
		for i in range(1, y + 1):
			if pieces[x, y-i]:
				if pieces[x, y-i].color != self.color:
					moves.add((x, y-i))
				break
			else:
				moves.add((x, y-i))
		
		# -x
		for i in range(1, x + 1):
			if pieces[x-i, y]:
				if pieces[x-i,y].color != self.color:
					moves.add((x-i,y))
				break
			else:
				moves.add((x-i,y))
		return set((x,y) for (x,y) in moves if 0 <= x < 8 and 0 <= y < 8)

class Bishop(Piece):
	model = "models/bishop"
	def validMoves(self, pieces):
		#diagonal
		x,y = self.square
		moves = set()
		for i in range(1, (min(8 - x, 8 - y)) + 1):
			if pieces[x+i, y+i]:
				if pieces[x+i, y+i].obj.getColor() != self.obj.getColor():
					moves.add((x+i, y+i))
				break
			else:
				moves.add((x+i, y+i))
		for i in range(1, (min(8 - x, y)) + 1):
			if pieces[x+i, y-i]:
				if pieces[x+i, y-i].obj.getColor() != self.obj.getColor():
					moves.add((x+i, y-i))
				break
			else:
				moves.add((x+i, y-i))
		for i in range(1, (min(x, 8 - y)) + 1):
			if pieces[x-i, y+i]:
				if pieces[x-i, y+i].obj.getColor() != self.obj.getColor():
					moves.add((x-i, y+i))
				break
			else:
				moves.add((x-i, y+i))
		for i in range(1, (min(x, y)) + 1):
			if pieces[x-i, y-i]:
				if pieces[x-i, y-i].obj.getColor() != self.obj.getColor():
					moves.add((x-i, y-i))
				break
			else:
				moves.add((x-i, y-i))
		
		return set((x,y) for (x,y) in moves if 0 <= x < 8 and 0 <= y < 8)
		
class Knight(Piece):
	model = "models/knight"
	def validMoves(self, pieces):
		x,y = self.square
		return set((i,j) for i in range(8) for j in range(8) if abs(i - x) * abs(j - y) == 2 and (not pieces[i,j] or pieces[i,j].obj.getColor() != self.obj.getColor()))
			
class Rook(Piece):
	model = "models/rook"
	def validMoves(self, pieces):
		x,y = self.square
		moves = set()
		# +y
		for i in range(1, 8 - y):
			if pieces[x, y+i]:
				if pieces[x, y+i].color != self.color:
					moves.add((x, y+i))
				break
			else:
				moves.add((x, y+i))
		# +x
		for i in range(1, 8 - x):
			if pieces[x+i, y]:
				if pieces[x+i,y].color != self.color:
					moves.add((x+i,y))
				break
			else:
				moves.add((x+i,y))
		
		# -y
		for i in range(1, y + 1):
			if pieces[x, y-i]:
				if pieces[x, y-i].color != self.color:
					moves.add((x, y-i))
				break
			else:
				moves.add((x, y-i))
		
		# -x
		for i in range(1, x + 1):
			if pieces[x-i, y]:
				if pieces[x-i,y].color != self.color:
					moves.add((x-i,y))
				break
			else:
				moves.add((x-i,y))
		
		return set((x,y) for (x,y) in moves if 0 <= x < 8 and 0 <= y < 8)

		
class SetupMenu:
	def __init__(self):
		self.showCSDialog()
	
	def showCSDialog(self):
		def submit(mode):
			d.removeNode()
			self.mode = mode
			if self.mode == SERVER:
				w = World(self.mode)
			else:
				self.showIPDialog()
				
		d = DirectDialog(dialogName='ClientServerDialog', text='Please choose:', buttonTextList=['Client', 'Server'], buttonValueList=[CLIENT, SERVER], command=submit, fadeScreen=1)
	
	def showIPDialog(self):
		def submitIP(addr):
			print addr
			ip.removeNode()
			self.ip = addr
			w = World(self.mode, self.ip)
			
		ip = DirectDialog(dialogName='IPDialog', text='Please enter the server IP address:', buttonTextList=[], buttonValueList=[], command=None, fadeScreen=1)
		tb = DirectEntry(text="", scale=.05, command=submitIP, initialText="", numLines=1, focus=1, pos=(-0.25,0,-0.15))
		tb.reparentTo(ip)
	
m = SetupMenu()
run()