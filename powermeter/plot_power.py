# create a data collection QtTimer and a plotting QtTimer
# 1. pull data from the powermeter at 10Hz and give it a timestamp
# 2. update the plot at 2Hz 0

# the powermeter data should just keep accumulating up to 1 million points

# the plot should have two regions, a bottom total timeline with a selectable sub-region
# the selected sub region is shown in the larger main window
#
# the GUI also should have options to restart the accumulation, change rate, save the current data to a csv file

# the plot should also have mean and standard deviation drawn calculated from the selected region
