#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3, time, random, math, os, binascii, re
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.collections as mc
from flask import Flask, url_for, request, jsonify
import asyncio
from flask_sock import Sock
# import websockets
# from flask_socketio import SocketIO
import json
from pymodbus.client import ModbusSerialClient


dbFile = "/Users/ryanlloydmiller/Grasp3Code/Grasp3Shapes.db"
# rs485Converter = '/dev/cu.usbserial-A10MIFNZ'
rs485Converter = '/dev/cu.usbserial-A10N7O4I'  #found using ls /dev/cu.*
socketConns=[]  # list of socket connection objects, 1 for each active client

activeDisplay = 0  # id number(s) of active display, useful for when client connects and needs to know status
activeShape = 0    # if we're using preset shapes (not individual pistons) this should hold that value
activePistons = '0' # string of 0s and 1s that holds status of all pistons
chansEach = 32 #chans available on each PLC

app = Flask(__name__)
sock = Sock(app)

global dest



def chk_conn_db(conn):
      try:
        conn.cursor()
        return True
      except Exception as ex:
        return False

def connect_RS485(baud=19200):
    client = ModbusSerialClient(method='rtu', port=rs485Converter, baudrate=baud, bytesize=8, parity='N', stopbits=1)
    client.connect() # should return true
    if client.is_socket_open():
        return client
    else:
        return False    
    
def change_PLC_baud(unitID, oldBaud = 9600, newBaud = 19200):
    # default is 9600 but I want 19200
    
    if newBaud == 19200:
        val = 4
    elif newBaud == 9600:
        val = 3
    
    client = connect_RS485(baud=oldBaud)
    result = client.write_register(address=254, value=val, unit=unitID)

    if result.isError():
        print('baud change failed')
    else:
        print('baud changed to ' + str(newBaud))
        print(result)
        
def set_all_pistons(plcID, direction):
    print(str(direction))
    if str(direction) == '1':
        val = 1792
    elif str(direction) == '0':
        val = 2048
        
    client = connect_RS485()
    client.write_register(address=1, value=val, unit=int(plcID))
    client.close() # not clear what this does
    
    response = jsonify(PLCChan=json.dumps('all'))
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response
        
        
def set_pistons_to_shape(shape, displayID):
    global activeShape, chansEach
    
    # error checking on input
    # if not str(direction) == '0' and not str(direction) == '1':
    #     response = jsonify(error='Direction must be 0 or 1')
    #     response.headers.add("Access-Control-Allow-Origin", "*")
    #     return response
    
    
    # Get the addresses of the relevant pistons
    cmd = f"SELECT PLC_ID, PLC_Chan FROM pistonAddressesTable WHERE DisplayID={displayID}"
    res = dest.execute(cmd).fetchall()
    if not res:
        print(res)
        print('failed to get it')
        return('failed to get piston addresses')
        
    # make sure we have the same numbers of piston positions and piston addresses
    if len(shape) != len(res):
        print('shape is different length than number of pistons')
        return('wrong shape for this display')

    # third convert everything to numpy arrays of ints
    PLCs = np.array(list(zip(*res))[0])       # grab 0th element from each tuple as PLC number
    pins = np.array(list(zip(*res))[1])       # grab 1st element from each tuple as pin number
    pos =  np.array(list(map(int, list(shape))))  # convert string of 0s and 1s to int list
    PLC_IDs = np.unique(PLCs)

    # make sure we can connect to RS485 modem
    client = connect_RS485()
    if not client:
        print('failed to connect to modem')
        return('Failed to connect to RS485 modem, using simulation mode...')
    
    
    # finally, work through list, one PLC at a time, and set pins
    for PLC in PLC_IDs:
        thesePins = pins[np.where(PLCs == PLC)]
        thesePos = pos[np.where(PLCs == PLC)]
        # if less than half the pistons are up, set all low and then individually step through
        if sum(thesePos) <= (chansEach/2):
            client.write_register(address=1, value=2048, unit=PLC) 
            pinsToChange = thesePins[np.where(thesePos == 1)]
            for pin in pinsToChange:
                client.write_register(address=pin, value=256, unit=PLC)
        
        # if at least half the pistons are up, set all high and then individually step through
        else: 
            client.write_register(address=1, value=1792, unit=PLC) 
            pinsToChange = thesePins[np.where(thesePos == 0)]
            for pin in pinsToChange:
                client.write_register(address=pin, value=512, unit=PLC)

    client.close() # not clear that this does anything worthwhile
    
    return('1')    


def local_copy_DB():
    global dest
    print(dest)
    
    if chk_conn_db(dest):
        dest.close()
        dest = []

    source = sqlite3.connect(dbFile)
    dest = sqlite3.connect(':memory:', check_same_thread=False)
    source.backup(dest)
    source.close()
    print(dest)
    # return dest

def backup_DB():
    import shutil
    dst = os.path.dirname(dbFile) + '/db_backup/'   # Destination path
    file_name, file_ext = os.path.splitext(os.path.basename(dbFile))  # Split the file name and extension
    new_file_name = file_name + "_copy"  # Create a variable to hold the new file name
    
    # Increment the file name until we find a free filename
    i = 1
    while os.path.exists(os.path.join(dst, new_file_name + file_ext)):
        new_file_name = "{}_copy_{}".format(file_name, i)
        i += 1
    
    shutil.copy(dbFile, os.path.join(dst, new_file_name + file_ext))  # Copy the file to the new location with the new file name


def create_hex_array(rMin=5, rAlwaysUp=7, rMax=25, pistonR = 1.1, pistonPitch=3.4):
    ## creates qrs coordinates for hex array that are within rMax (mm) and outside rMin (mm)
    #  and then saves it to the database
    #  pistons closer than alwaysUp (mm) are labeled as such in the DB
    

    global dest # we need to update the in-memory db connection after this
    global chansEach
    mult = pistonPitch / 1.1547  # with pistons spaced every 1 unit on qrs grid, that's 1.15 on cartesian
    sin60 = np.sin(np.radians(60)) # used for figuring out the y position of each piston
    
    con = sqlite3.connect(dbFile)
    cur = con.cursor()
    
    # figure out what id to use for the new display
    try:
        res = cur.execute("Select MAX(DisplayID) from displayPropsTable").fetchall()
        newDisplayID = res[0][0] + 1
    except:
        newDisplayID = 1
    print(newDisplayID)
    
    # find all piston positions that meet criteria and put in disk database
    # addys = np.array([], dtype=np.short).reshape(0,3); # init the array that will hold QRSs
    piston = 0  # piston ID incrementer
    plc = 1     # PLC ID incrementer
    chan = 1    # PLC Chan incrementer
    zone = 0    # 0: inside Min, 1: maybe usable, 2: outside Max
    qrsRad = 0  # step from inside to outside, construct this ring, check where we are
    
    
    while not zone == 2:
        QRS = get_QRS(qrsRad);           # QRS values of everything in this ring
        xs = QRS[:,0] * mult;
        ys = 2. * sin60 * (QRS[:,1] - QRS[:,2]) / 3. * mult; 
        dists = np.sqrt(xs**2 + ys**2);
        
        alwaysUps = np.logical_and(dists >= rMin, dists <= rAlwaysUp)
        sometimesUps = np.logical_and(dists > rAlwaysUp, dists < rMax)
        
        if zone == 0 and (alwaysUps.any() or sometimesUps.any()):
            zone = 1
        elif zone == 1 and not alwaysUps.any() and not sometimesUps.any():
            zone = 2
            break
        
        
        # Step through each pin address
        for i in range(np.size(QRS,0)):
            alwaysUp = 1 if alwaysUps[i] else 0

            if alwaysUps[i] or sometimesUps[i]:
                piston += 1
                cur.execute("INSERT INTO pistonAddressesTable VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [newDisplayID, piston, plc, chan, int(QRS[i,0]), int(QRS[i,1]), int(QRS[i,2]), round(xs[i], 3), round(ys[i], 3), alwaysUp])  

                chan += 1
                if chan > chansEach:
                    chan = 1
                    plc += 1
                    
        qrsRad += 1

    # make the vacuum channel the last channel on the current PLC unless it's already taken, in which case wrap around to next PLC
    vacChan = chansEach
    if chan == chansEach:
        plc += 1

    cur.execute("INSERT INTO displayPropsTable VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [newDisplayID, piston, plc, rMin, rAlwaysUp, rMax, pistonR, pistonPitch, plc, vacChan])
    con.commit()
    con.close()   
    
    # update the in-memory db connection
    local_copy_DB() 
    
    print('Stored ' + str(piston) + ' pistons as array ' + str(newDisplayID))
    
    return newDisplayID
    

    
        
def get_hex_array(displayID, style='qrs'):
    
    if style == 'qrs':
        cmd = f"SELECT q, r, s FROM pistonAddressesTable WHERE DisplayID='{str(displayID)}'"
    elif style=='xy':
        cmd = f"SELECT piston, x, y, AlwaysUp FROM pistonAddressesTable WHERE DisplayID='{str(displayID)}'"
        
    return dest.execute(cmd).fetchall()



def get_display_IDs():
    global dest
    print(dest)
    cmd = f"SELECT DisplayID FROM displayPropsTable"
    return dest.execute(cmd).fetchall()
    


def get_hex_array_props(displayID):
    cmd = f"SELECT nPins, rMin, rMax, pistonR FROM displayPropsTable WHERE DisplayID='{str(displayID)}'"
    return dest.execute(cmd).fetchall()


def delete_hex_array(displayID = 100000):
    global dest # we need to update the in-memory db connection after this
    con = sqlite3.connect(dbFile)
    con.cursor().execute(f"DELETE FROM pistonAddressesTable WHERE DisplayID={displayID}")
    con.cursor().execute(f"DELETE FROM displayPropsTable WHERE DisplayID={displayID}")
    con.cursor().execute(f"DELETE FROM shapeTable WHERE DisplayID={displayID}")
    con.commit()
    con.close()
    
    local_copy_DB() # update the in-memory db connection



def get_shape_IDs(displayID):
    cmd = f"SELECT shapeID FROM shapeTable WHERE DisplayID={displayID}"
    return dest.execute(cmd).fetchall()


def get_shape(shapeID=2, col='shapeFull', plot=0):
    ## Get the piston configuration from the database and return it as a binary string
    #  ensure that the shape is compatible with the chosen display
    global activePistons
    cmd = f"SELECT shapeBits, {col} , DisplayID FROM shapeTable WHERE shapeID='{shapeID}'"
    res = dest.execute(cmd).fetchall()
    activePistons = bytes_to_binary_string(res[0][0], res[0][1])
    displayID = res[0][2]
    
    if len(res):
        return activePistons, displayID
    else:
        return '0'
    
def reset_DB():
    global dest # we need to update the in-memory db connection after this
    
    backup_DB()      # copy file to new file in backup folder
    
    # delete db entries
    con = sqlite3.connect(dbFile)
    con.cursor().execute(f"DELETE FROM pistonAddressesTable")
    con.cursor().execute(f"DELETE FROM displayPropsTable")
    con.cursor().execute(f"DELETE FROM shapeTable")
    con.cursor().execute(f"UPDATE sqlite_sequence SET seq = 0 WHERE name = 'shapeTable'")
    con.commit()
    con.close()
    
    local_copy_DB() # update the in-memory db connection
    
    
    
    
# def plotHapticDisplay(shape=bin(0)[2:].zfill(1000)):
#     ## plots the specified shape on the specified display given the specified hex grid
        
#     # calculate multiplier used for plotting grid in cartesian coords
#     mult = self.pistonPitch / 1.1547  # with pistons spaced every 1 unit on qrs grid, that's 1.15 on cartesian
        
#     # convert to numpy array and calculate cartesian y value
#     y_cart = 2. * np.sin(np.radians(60)) * (self.hexArray[:,2] - self.hexArray[:,3]) / 3
#     xy = np.transpose([self.hexArray[:,1] * mult, y_cart * mult])
    
    
#     # plot
#     fig, ax = plt.subplots()
#     ax.add_patch(plt.Circle((0, 0), self.vaccuumR, color='k', fill=False))
#     ax.add_patch(plt.Circle((0, 0), self.outerR, color='r', fill=False))  
    
#     # plot pistons according to whether active or not
#     for i in range(np.size(self.hexArray,0)):
#         if shape[i] == '0':
#             ax.add_patch(plt.Circle((xy[i]), self.pistonR, color='k', fill=False))
#         else:
#             ax.add_patch(plt.Circle((xy[i]), self.pistonR*1.8, color='k', fill=True))    
    
#     ax.axis('equal')
#     ax.autoscale()
#     plt.show()
        
    
def get_QRS(rad):
    # return array of size n x 3 holding Q, R, and S vals at requested radius
    
    if rad == 0: return np.array([[0, 0, 0]])
    
    down = np.arange(rad, 0, -1);               # rad:1
    up = np.arange(0, rad, 1);                  # 0:rad-1
    high = (np.ones(rad) * rad).astype(int);    # rads
    
    qs = np.concatenate([down-rad, high*-1, down*-1, up, high, down])
    rs = np.concatenate([high, down, down-rad, high*-1, down*-1, up])
    
    return np.transpose(np.array([qs, rs, (qs+rs) * -1]))
        
        
def binary_string_to_bytes(binary):
    bit_count = len(binary)
    byte_count = math.ceil(bit_count / 8)
    return int(binary, 2).to_bytes(byte_count, 'little')

def bytes_to_binary_string(nBits, byteString):
    integer = int.from_bytes(byteString, 'little')
    return f'{integer:0{nBits}b}'


    


def check_neighbor(target,q,r,s):
    # checks to see if the specified piston is in the target array
    return np.sum(np.logical_and(target[:,0]==q, target[:,1]==r, target[:,2]==s))

def create_shape(displayID=1):
    ## Select pistons to be high
    ##   and store in database as integer string
    ##   returns the shapeID of the new shape
    
    # get the properties for this display
    con = sqlite3.connect(dbFile)
    qrs = con.cursor().execute(f"SELECT q, r, s, AlwaysUp FROM pistonAddressesTable WHERE DisplayID='{displayID}'").fetchall()
    qrs = np.array(qrs)
    alwaysUpIndices = np.where(qrs[:,3])[0].tolist()
    
    # build the shape
    binary = '0'*len(qrs)
    binary = fill_always_up(binary, alwaysUpIndices)
    binary = add_arms(qrs, alwaysUpIndices, binary)
    binary = fill_holes(qrs, binary)     
    minNeighbor = 0 if len(binary) < 20 else 1  # this avoids situation where small displays get all fingers removed
    binary = remove_fingers(qrs, binary, minNeighbor)
    byteString = binary_string_to_bytes(binary)

    # put the new shape in the database
    con.cursor().execute("INSERT INTO shapeTable(DisplayID, shapeBits, shapeFull) VALUES(?, ?, ?)", (displayID, len(binary), byteString))
    newShapeID = con.cursor().execute("Select MAX(shapeID) from shapeTable").fetchall()[0][0]
    con.commit()
    con.close()
    
    print('Added shape ' + str(newShapeID))    
    
    # update the in-memory db connection
    local_copy_DB() 
    
    return newShapeID

def fill_always_up(binary, alwaysUpIndices):
    # Set all the middle pins high
    
    for i in alwaysUpIndices:
        binary = binary[:i] + '1' + binary[i+1:] 
    return binary

def add_arms(qrs, fingerStarts, binary):
    
    for i in fingerStarts:
        q, r, s = qrs[i,0:3]
        
        cont = 1     
        while cont == 1:
            # there are 6 pistons surrounding this
            # check each one to see if it's (a) further away and (b) in the array
            
            # these are the 6 neighboring pistons
            qrsOptions = np.array([[q+1, r-1, s], [q-1, r+1, s],[q-1, r, s+1],[q+1, r, s-1], [q, r+1, s-1], [q, r-1, s+1]])
            
            # indices of qrsOptions that are beside or outside the current pin
            notIn = np.where(np.sum(np.abs(qrsOptions),1) >= (abs(q) + abs(r) + abs(s)))
                        
            # check each of the 4 or 5 remaining options to see if it's in the array
            # if so, add it to a list from which we will randomly select one
            options = []
            for ii in notIn[0]:
                if check_neighbor(qrs, qrsOptions[ii,0], qrsOptions[ii,1], qrsOptions[ii,2]):
                    options.append(ii)
                    
            # if we're on the edge
            if len(options) < 3:
                cont = 0
                continue
               
            # randomly choose one of the options and move there
            newPositionQRS = qrsOptions[np.random.choice(options)]
            q, r, s = newPositionQRS
            newIndex = np.where(np.logical_and(qrs[:,0]==q, qrs[:,1]==r, qrs[:,2]==s))[0][0]
            
            # update this position to being active
            binary = binary[:newIndex] + '1' + binary[newIndex+1:] 
        
    return binary


def remove_fingers(qrs, binary, minNeighbors=1):
    # recursively check any active piston to make sure it has at least minNeighbors neighbors
    
    keepGoing = True
    while keepGoing:

        # get the addresses of pistons that are active and inactive for this shape
        qrsActive = qrs[[m.start() for m in re.finditer('1', binary)]]
        qrsInactive = qrs[[m.start() for m in re.finditer('0', binary)]]
        
        pistonsChanging = 0
        for i in range(len(qrsActive)):
            q, r, s = qrsActive[i,0:3]
            
            ns = 0
            ns += check_neighbor(qrsActive, q-1, r+1, s)
            ns += check_neighbor(qrsActive, q+1, r-1, s)
            ns += check_neighbor(qrsActive, q-1, r, s+1)
            ns += check_neighbor(qrsActive, q+1, r, s-1)
            ns += check_neighbor(qrsActive, q, r+1, s-1)
            ns += check_neighbor(qrsActive, q, r-1, s+1)
            
            if ns <= minNeighbors:
                pistonsChanging += 1
                # find position in binary (s) corresponding to this qrs address and change it to 1     
                ind = int(np.argwhere(np.logical_and(qrs[:,0]==q, qrs[:,1]==r, qrs[:,2]==s)))
                binary = binary[:ind] + '0' + binary[ind+1:] 

        if pistonsChanging == 0:
            keepGoing = False
            
    return binary
    
    


def fill_holes(qrs, binary, minNeighbors = 4):
    # recursively check any inactive piston to make sure it has at most minNeighbors neighbors
    # TODO: this wont fill large holes sometimes found in large displays
    
    keepGoing = True
    while keepGoing:

        # get the addresses of pistons that are active and inactive for this shape
        qrsActive = qrs[[m.start() for m in re.finditer('1', binary)]]
        qrsInactive = qrs[[m.start() for m in re.finditer('0', binary)]]
        
        pistonsChanging = 0
        for i in range(len(qrsInactive)):
            q, r, s = qrsInactive[i,0:3]
            
            ns = 0
            ns += check_neighbor(qrsActive, q-1, r+1, s)
            ns += check_neighbor(qrsActive, q+1, r-1, s)
            ns += check_neighbor(qrsActive, q-1, r, s+1)
            ns += check_neighbor(qrsActive, q+1, r, s-1)
            ns += check_neighbor(qrsActive, q, r+1, s-1)
            ns += check_neighbor(qrsActive, q, r-1, s+1)
            
            if ns >= minNeighbors:
                pistonsChanging += 1
                # find position in binary (s) corresponding to this qrs address and change it to 1     
                ind = int(np.argwhere(np.logical_and(qrs[:,0]==q, qrs[:,1]==r, qrs[:,2]==s)))
                binary = binary[:ind] + '1' + binary[ind+1:] 

        if pistonsChanging == 0:
            keepGoing = False
            
    return binary

global dest
source = sqlite3.connect(dbFile)
dest = sqlite3.connect(':memory:', check_same_thread=False)
source.backup(dest)
source.close()



def broadcast(message = "test"):
    # send message to all connected websocket clients
    # if there's an error, remove that connection from the list
    for ws in socketConns:
        try:
            ws.send(message)
        except:
            socketConns.remove(ws)
            
def broadcastDisplay():
    global activeDisplay, activePistons
    if activeDisplay:
        broadcast('{"activeDisplay":' + str(activeDisplay) + ', "activeShape":' + str(activeShape) + ', "activePistons":"' + activePistons + '"}')
    else:
        print('No active displays')


@sock.route('/')
def echo(ws):
    # When a websocket connection is made from a client, add that WS connection
    # to my list 'socketConns' that will be used for broadcasting
    # also echo back whatever the client sends
    
    socketConns.append(ws)
    broadcastDisplay()

    while True:
        data = ws.receive()
        print(data)
        
        if data == 'ping':
            ws.send('__pong__')
            print('got a ping')
        else:
            ws.send(data)
        
        


@app.route('/')
def index():
    return 'hello world'

@app.route('/display/<displayID>/<passiveUpdate>', methods = ['GET', 'POST', 'DELETE'])
def display(displayID, passiveUpdate):
    if request.method == 'GET':
        global activeDisplay, activePistons
        activeDisplay = displayID  
        if not passiveUpdate:
            activePistons = '0'   # when client actively changes shape, reset activePistons
        broadcastDisplay()
        
        xys = get_hex_array(displayID, 'xy')
        hap = get_hex_array_props(displayID)
        
        response = jsonify(xys=json.dumps(xys), nPins=hap[0][0], rMin=hap[0][1], rMax=hap[0][2], pistonR=hap[0][3])
        response.headers.add("Access-Control-Allow-Origin", "*")
        return response
        
    
    elif request.method == 'POST':
        rMin = float(request.form.get('rMin'))
        rAlwaysUp = float(request.form.get('rAlwaysUp'))
        rMax = float(request.form.get('rMax'))
        pistonR = float(request.form.get('pistonR'))
        pistonPitch = float(request.form.get('pistonPitch'))
        
        dispID = create_hex_array(rMin, rAlwaysUp, rMax, pistonR, pistonPitch)
        
        response = jsonify(displayID=json.dumps(dispID))
        response.headers.add("Access-Control-Allow-Origin", "*")
        return response

    elif request.method == 'DELETE':
        delete_hex_array(displayID)
        return "display deleted"
    
@app.route('/shape/<ID>', methods = ['GET', 'POST', 'DELETE'])
def shape(ID):
    if request.method == 'GET':
        global activePistons, activeShape
        activeShape = ID
        
        # shape 0 is for blanking out the display
        if activeShape == '0':
            print('blanking out display...')
            
            # figure out how many PLCs we need to blank out
            global activeDisplay
            cmd = f"SELECT nPLCs FROM displayPropsTable WHERE DisplayID={activeDisplay}"
            nPLCs = dest.execute(cmd).fetchall()[0][0]

            for i in range(nPLCs):
                set_all_pistons(i+1, 0)
            
            resp = "1"
        # otherwise get the shape info and set the pistons accordingly    
        else:
            activePistons, displayID = get_shape(ID)
            resp = set_pistons_to_shape(activePistons, displayID)
            
        broadcastDisplay()
        
        if resp == "1":
            response = jsonify(shape=json.dumps(activePistons))
        else:
            response = jsonify(shape=json.dumps(activePistons), error=resp)
            
        response.headers.add("Access-Control-Allow-Origin", "*")
        return response
            
        
    
    elif request.method == 'POST':
        print('were posting')
        print(request.form)
        
        displayID = float(request.form.get('displayID'))
        newShape = create_shape(displayID)
        
        response = jsonify(newShape=json.dumps(newShape))
        response.headers.add("Access-Control-Allow-Origin", "*")
        return response
        
    elif request.method == 'DELETE':
        # delete_hex_array(displayID)
        return "display deleted"


@app.get('/get_display_IDs')
def get_display_IDsHTTP():
    IDs = get_display_IDs()
    client = connect_RS485()
    if not client:
        print('failed to connect to modem')
        response = jsonify(DisplayIDs=json.dumps(IDs), error='Failed to connect to RS485 modem, using simulation mode...')
    else:
        response = jsonify(DisplayIDs=json.dumps(IDs))
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response

@app.get('/get_shape_IDs/<displayID>')
def get_shape_IDs_HTTP(displayID):
    IDs = get_shape_IDs(displayID)
    response = jsonify(ShapeIDs=json.dumps(IDs))
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response

@app.get('/set_piston/<displayID>/<piston>/<direction>')
def set_piston_HTTP(displayID, piston, direction):
    global activeDisplay, activePistons
    # error checking on input
    if not str(direction) == '0' and not str(direction) == '1':
        response = jsonify(error='Direction must be 0 or 1')
        response.headers.add("Access-Control-Allow-Origin", "*")
        return response

    # First, get the info for the piston we want to change
    # Check for special case of a request for the vacuum channel
    print(type(piston))
    print(piston)
    if piston == "-1":
        cmd = f"SELECT vacPLC, vacChan FROM displayPropsTable WHERE DisplayID='{displayID}'"
    else:
        cmd = f"SELECT PLC_ID, PLC_Chan FROM pistonAddressesTable WHERE DisplayID='{displayID}' AND piston='{piston}'"
    res = dest.execute(cmd).fetchall()
    if not res:
        response = jsonify(error='Specified piston does not exist in db for this shape')
        response.headers.add("Access-Control-Allow-Origin", "*")
        return response
        
    PLC_ID = res[0][0]
    PLC_Chan = res[0][1]
    print('plc: ' + str(PLC_ID) + ", chan: " + str(PLC_Chan) + ", direction: " + str(direction))
    
    val = 512 - 256 * int(direction)  #512 for down, 256 for up
    
    # Second, send the request to the PLC
    client = connect_RS485()
    if client:
        result = client.write_register(address=PLC_Chan, value=val, unit=PLC_ID)

        if result.isError():
            response = jsonify(error='PLC request failed')
        else:
            response = jsonify(PLCChan=json.dumps([res[0], direction]))
        
        client.close() # not clear that this does anything worthwhile
        
    else:
        response = jsonify(error="Couldn't connect to the RS485 modem, using simulation mode...")
    
    # Third, tell the client how we did
    response.headers.add("Access-Control-Allow-Origin", "*")
    activeShape = 0
    # activeDisplay[piston] = direction
    
    activeDisplay = activeDisplay[:int(piston)] + str(direction) + activeDisplay[int(piston)+1:]
    
    broadcastDisplay()
    return response







