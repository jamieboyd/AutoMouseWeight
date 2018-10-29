#!/usr/bin/python3 
# -*-coding: UTF-8 -*-
from array import array
import numpy as np
import json

# constants for weight analysis
kMIN_WEIGHT = 15.5 # weights below this value are excluded
kMAX_WEIGHT = 40.5 # weights above this value are excluded
kHIST_BINSIZE = 0.1 # width of the bins in the cumulative histogram, in grams
kKERNEL_WIDTH = 17 # width of the smoothing kernel used for the derivative of the histogram
kN_SMOOTH = 5 # number of times the smoothing kernel is applied to the derivarive

def get_day_weights (folder_path, cageName, date_year, date_month, date_day, output_path, doPlots, emailDict):
    # ensure paths end in forward slash, but don't add a second forward slash
    if not folder_path.endswith ('/'):
        folder_path.append ('/')
    if not output_path.endswith ('/'):
        output_path.append ('/')
    date_string = str (date_year) + '_' + '{:02}'.format(date_month)  + '_' + '{:02}'.format (date_day)
    filename = folder_path + cageName + '_' + date_string
    # start with an empty array of floats, and append the binary data from the file to it
    data = array ('f', [])
    with open (filename, 'rb') as binaryFile:
        try:
            data.frombytes (binaryFile.read())
        except ValueError as e:
            print ('Error getting data from binary file:' + str (e))
            raise e
    # import matplotlib for making plots
    if doPlots:
        import matplotlib.pyplot as plt
    sendMail = False
    if emailDict is not None:
        sendMail = True
        kFROMADDRESS = emailDict.get ('Email From Address')
        kRECIPIENTS = emailDict.get ('Email Recipients')
        kPASSWORD = emailDict.get ('Email Password')
        kSERVER = emailDict.get ('Email Server')
        import smtplib
        from email.mime.text import MIMEText
        SUBJECT = 'Weights for ' + cageName + ' on ' + str (date_year) + '/' + '{:02}'.format(date_month)  + '/' + '{:02}'.format (date_day)
        def emailWeights (SUBJECT, file_name):
            with open (file_name) as fp:
                print ("get day weights filename to email = ", file_name)
                msg = MIMEText(fp.read())
                msg['Subject'] = SUBJECT
                msg['From'] = kFROMADDRESS
                # Send the mail
                try:
                    server = smtplib.SMTP(kSERVER)
                    server.starttls()
                    server.login(kFROMADDRESS, kPASSWORD)
                    msg['To']= ', '.join(kRECIPIENTS)
                    server.sendmail(msg.get('From'), kRECIPIENTS, msg.as_string())
                    server.quit()
                except Exception as e:
                    print ("Emailing weights failed:" + str (e))
                        #sendMail = False
    # dictionaries to store entries, arrays for weights, and prehaps indices of raw traces for each mouse
    #in each case keys are id_codes
    sorted_data = {}    # each value is array of all raw weigths for the mouse
    entry_data = {}     # each value is number of tube entries for the mouse
    if doPlots:
        run_starts = {} # each value is array of indices from the raw data for start and end positions of each tube traversal for mouse
    # iterate through each epoch of data, binning and adding data to the dictionary for each mouse
    nPnts = len (data)
    iPt =0
    while iPt < nPnts:
        # first point is mouse RFID code, in negative for easier parsing
        id_code= 'm' + str (int(-data[iPt]))
        # second point is time, in seconds since midnight, which we don't care about when parsing a single file
        iPt +=2
        startPt = iPt
        if not id_code in sorted_data:
            sorted_data [id_code] = array ('f', [])
            entry_data [id_code] = 1
        else:
            entry_data[id_code] += 1
        # find end of this run of data
        while iPt < nPnts -1 and data [iPt + 1] > -250:
            iPt += 1
        if iPt == nPnts -1:
            iPt +=1                                                                                                                                                                                      
        # copy data
        for oPt in range (startPt, iPt, 1):
            if data [oPt] > kMIN_WEIGHT and data [oPt] < kMAX_WEIGHT:
                sorted_data[id_code].append(data [oPt])
        # save positions for plotting
        if doPlots:
            if not id_code in run_starts:
                run_starts [id_code]=array ('i', [])
            run_starts [id_code].append(startPt)
            # last point is last value for plotting
            run_starts [id_code].append(iPt)
        # move to next run of data
        iPt +=1
    # data for this day is now sorted by mouse
    # now process data for each mouse
    file_name = output_path + cageName + '_weights_' + date_string + '.txt'
    histNumBins = int ((kMAX_WEIGHT- kMIN_WEIGHT)/kHIST_BINSIZE)
    kernel = gKernel (kKERNEL_WIDTH)
    with open (file_name, 'w') as out_file:
        out_file.write ('mouse\tentries\tweight\r')
        for id_code in sorted(sorted_data.keys()):
            if len (sorted_data[id_code]) < 5:
                result = float ('nan')
                entries =0
            else:
                # copy array into numpy array for histogram and gradient
                numArray = np.array (sorted_data[id_code], dtype=np.float32)
                # make histogram of data for this mouse - hist is the data, WtVals is the bin boundaries
                hist, WtVals=np.histogram (numArray,range =(kMIN_WEIGHT, kMAX_WEIGHT), bins = histNumBins)
                # make histogram cumulative. Part of histogram with most data will have steepest slope
                cumulative = np.cumsum(hist)
                # make derivative of histogram to find part with steepest slope
                diffArray = np.gradient(cumulative, 2)
                # smooth the derivative lots
                for smooth in range (0, kN_SMOOTH,1):
                    diffArray=np.convolve (diffArray, kernel, mode = 'same')
                # find the location of the maximum value in the histogram
                position = np.argmax (diffArray)
                # The center of the bin containing the max value is returned as the result
                result = (WtVals [position] + WtVals [position + 1])/2
                entries = entry_data [id_code]
            if doPlots:
                print (id_code, str (entries), '{:.2f}'.format (result))
                mRunStarts =run_starts [id_code]
                for entry in range (0, entries):
                    firstPt = mRunStarts [2*entry]
                    lastPt = mRunStarts [(2*entry) +1]
                    plt.plot (data[firstPt:lastPt])
                plt.show()
                plt.plot(WtVals[:-1], diffArray)
                plt.show()
            out_file.write (id_code + '\t') 
            out_file.write (str (entries) + '\t')
            out_file.write ('{:.1f}'.format (result) + '\n' )
            #out_file.flush()
    if sendMail:
        emailWeights (SUBJECT, file_name)



# makes a Gaussian kernel using Pascal's triangle
def gKernel (nK):
    kernel = np.zeros([nK], dtype = np.float32)
    kernel [0] = (1/2)**(nK -1)
    for ii in range (1,nK, 1):
        for ij in range (nK-1, 0, -1):
            kernel [ij] += kernel[ij-1]
    return kernel


"""
Sample usage of the program
"""

if __name__ == '__main__':
    kDATA_FOLDER = '/home/pi/Documents/AutoMouseWeightData/'       #where data files are located
    kOUTPUT_FOLDER = '/home/pi/Documents/AutoMouseWeightData/'     # where text files are saved
    kCAGE_NAME = 'cage5'                                           # names of data files start with cage name

    kDO_PLOTS = False # program will stop and display plots of raw data and smoothed derivative
    kSEND_MAIL = None # make a dictionary with email adress and server info to send email, not likely if running standalone

    while True:
        year = 0
        while year < 2000 or year > 2020:
            year = int (input ('Year = '))
        month =0
        while month < 1 or month > 12:
             month = int (input ('Month = '))
        day = 0
        while day < 1 or day > 31:
            day = int (input ('Day='))
            
        get_day_weights (kDATA_FOLDER, kCAGE_NAME, year, month , day, kOUTPUT_FOLDER, kDO_PLOTS, kSEND_MAIL)

