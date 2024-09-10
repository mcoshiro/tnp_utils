"""@package docstring
Package containing analyzer that can be used for tag-and-probe analyses

For CMS members, see https://twiki.cern.ch/twiki/bin/view/CMS/ElectronScaleFactorsRun2
                 and https://indico.cern.ch/event/1288547/contributions/5414376/attachments/2654622/4597206/26052023_RMS_EGamma.pdf
                 and https://indico.cern.ch/event/1360957/contributions/5994827/attachments/2873039/5030766/SF2022update_fnal.pdf
"""

import json
import math
import os
import ROOT
from tnp_utils import *

ROOT.gROOT.LoadMacro('./lib/tnp_utils.cpp')

#rng = ROOT.TRandom3()

class TnpAnalyzer:
  '''
  Class used to do a T&P analysis. See scripts/example.py for example usage.
  '''

  def __init__(self, name):
    '''
    Default constructor

    name  string, name for this tnp_analysis, used in temp file names
    '''
    self.temp_name = name
    self.fit_var_name = ''
    self.fit_var_nbins = 0
    self.fit_var_range = (0.0,0.0)
    self.fit_var_weight = '1'
    self.preselection = '1'
    self.preselection_desc = ''
    self.measurement_variable = '1'
    self.bin_selections = []
    self.bin_names = []
    self.nbins = 0
    self.nbins_x = 0
    self.input_filenames = []
    self.tree_name = ''
    self.temp_file = None
    self.model_initializers = dict()
    self.param_initializers = dict()
    self.flag_set_input = False
    self.flag_set_fitting_variable = False
    self.flag_set_measurement_variable = False
    self.flag_set_binning = False


  def set_input_files(self, filenames, tree_name):
    '''
    Sets input file

    filenames  list of strings, name of input files
    tree_name  string, name of TTree in file
    '''
    self.input_filenames = filenames
    self.tree_name = tree_name
    self.flag_set_input = True

  def set_fitting_variable(self, name, description, nbins, 
                           var_range, weight='1'):
    '''
    Adds information about fitting variable

    name         string, name of branch in TTree or C++ expression
    description  string, name used in plots (with TLaTeX)
    nbins        int, number of bins to use for fit variable
    var_range    tuple of two floats, start and end of fit range
    weight       string, expression for weight to use
    '''
    self.fit_var_name = name
    self.fit_var_desc = description
    self.fit_var_nbins = nbins
    self.fit_var_range = var_range
    self.fit_var_weight = weight
    self.flag_set_fitting_variable = True

  def set_measurement_variable(self, var):
    '''
    Sets selection efficiency to measure with tag & probe

    var  string, name of branch in TTree or C++ expression
    '''
    self.measurement_variable = var 
    self.flag_set_measurement_variable = True

  def set_preselection(self, preselection, desc):
    '''
    Sets basic preselection applied to all bins

    preselection  string, selection as a C++ expression
    desc          string, description of selection in TLaTeX
    '''
    self.preselection = preselection
    self.preselection_desc = desc

  @staticmethod
  def make_nd_bin_dimension(name, description, edges):
    '''
    Generates a dimension for an even ND binning

    name         string, name of branch in TTree or C++ expression
    description  string, name used in plots (with TLaTeX)
    edges        list of floats, bin edges
    '''
    return (name, description, edges)

  def add_nd_binning(self,dimensions):
    '''
    Sets even n-dimensional binning for TnP analysis

    dimensions  list of tuples generated by make_nd_bin_dimension
    '''
    #calculate number of bins
    ndims = len(dimensions)
    self.nbins = 1
    self.nbins_x = len(dimensions[0][2])-1
    for dim in dimensions:
      self.nbins *= (len(dim[2])-1)

    #initialize each bin (which is just a selection and a name)
    for ibin in range(0,self.nbins):
      bin_selection = ''
      bin_name = ''
      remaining_dim_index = ibin
      for idim in range(len(dimensions)):
        this_dim = dimensions[ndims-idim-1]
        this_dim_len = len(this_dim[2])-1
        dim_index = remaining_dim_index % this_dim_len
        if idim != 0:
          bin_selection += '&&'
          bin_name += ', '
        bin_selection += (str(this_dim[2][dim_index])+'<'+this_dim[0])
        bin_selection += ('&&'+this_dim[0]+'<'+str(this_dim[2][dim_index+1]))
        bin_name += (str(this_dim[2][dim_index])+' < '+strip_units(this_dim[1]))
        bin_name += (' < '+str(this_dim[2][dim_index+1])+' '+get_units(this_dim[1]))
        remaining_dim_index //= this_dim_len
      self.bin_selections.append(bin_selection)
      self.bin_names.append(bin_name)
    self.flag_set_binning = True

  def add_custom_binning(self, bin_selections, bin_names):
    '''
    Creates custom bins for TnP analysis

    bin_selections  list of strings, describes selection for each bin
    bin_names       list of strings, names of each bin that appear in plots
    '''
    self.nbins = len(bin_selections)
    self.bin_selections = bin_selections
    self.bin_names = bin_names
    self.flag_set_binning

  def add_model(self, model_name, model_initializer):
    '''
    Adds an initializer for a RooWorkspace, i.e. signal and background shapes
    with appropriate Parameters. See below for examples of model initializers
    The model must take as an argument the fitting variable (as a RooRealVar)
    as well as the bin number and include RooRealVars nSig and nBkg 
    representing the norm of signal and background as well as a RooRealVar 
    fit_var representing the fit variable and a RooAbsPdf pdf_sb representing 
    the S+B model

    model_name         string, name for this model
    model_initializer  function that returns RooWorkspace, see examples
    '''
    self.model_initializers[model_name] = model_initializer

  def add_param_initializer(self, name, param_initializer):
    '''
    Adds a parameter initializer for a RooWorkspace, i.e. a function that
    takes in the bin number, a bool representing probe pass/fail, and a 
    workspace that sets the parameter values for the workspace

    name               string, name for the parameter initializer
    param_initializer  function that sets Workspace parameters
    '''
    self.param_initializers[name] = param_initializer

  def get_binname(self, ibin):
    return clean_string(self.bin_selections[ibin])

  def make_simple_tnp_plot(self, workspace, canvas):
    '''
    Draws a simple plot for debugging fits

    workspace  T&P RooWorkspace
    canvas     TCanvas to draw plot on
    '''
    plot = workspace.var('fit_var').frame()
    workspace.data('data').plotOn(plot)
    pdf_sb = workspace.pdf('pdf_sb')
    pdf_sb.plotOn(plot,ROOT.RooFit.Name('fit_sb'))
    sig_norm_temp = workspace.var('nSig').getValV()
    bak_norm_temp = workspace.var('nBkg').getValV()
    workspace.var('nSig').setVal(0.0)
    pdf_sb.plotOn(plot,ROOT.RooFit.Normalization(bak_norm_temp/(sig_norm_temp+bak_norm_temp),ROOT.RooAbsReal.Relative),ROOT.RooFit.Name('fit_b'))
    workspace.var('nSig').setVal(sig_norm_temp)
    canvas.cd()
    plot.Draw()
    canvas.Update()

  def check_initialization(self):
    #check things that are needed are already set
    if ((not self.flag_set_input) or
        (not self.flag_set_fitting_variable) or
        (not self.flag_set_measurement_variable) or
        (not self.flag_set_binning):
      raise ValueError('Must initialize binning, fit variable, measurement, '+
                       'input files, and model before calling run methods.')

  def initialize_files_directories(self):
    '''
    generates output file and directory if they do not already exist
    '''
    #make output directory if it doesn't already exist
    if not os.path.isdir('out'):
      os.mkdir('out')
    elif not os.path.isdir('out/'+self.temp_name):
      print('Output directory not found, making new output directory')
      os.mkdir('out/'+self.temp_name)

    #open working (swap/temp) file
    temp_file_name = 'out/'+self.temp_name+'/'+self.temp_name+'.root'
    if not os.path.isfile(temp_file_name):
      print('Temp ROOT file not found, making new temp file.')
      self.temp_file = ROOT.TFile(temp_file_name,'CREATE')
    else:
      if self.temp_file == None:
        self.temp_file = ROOT.TFile(temp_file_name,'UPDATE')

  def produce_histograms(self):
    '''
    Processes the input file(s) and generates histograms for use in fitting
    '''
    self.check_initialization()
    self.initialize_files_directories()
    print('Preparing file(s) for processing.')
    filenames_vec = ROOT.std.vector('string')()
    for filename in self.input_filenames:
      filenames_vec.push_back(filename)
    df = ROOT.RDataFrame(self.tree_name,filenames_vec)
    df = df.Filter(self.preselection)
    df = df.Define('tnpanalysis_fit_var', self.fit_var_name)
    df = df.Define('tnpanalysis_fit_var_weight', self.fit_var_weight)
    pass_hist_ptrs = []
    fail_hist_ptrs = []
    for ibin in range(0,self.nbins):
      df_bin = df.Filter(self.bin_selections[ibin])
      df_bin_pass = df_bin.Filter(self.measurement_variable)
      df_bin_fail = df_bin.Filter('!('+self.measurement_variable+')')
      pass_hist_ptrs.append(df_bin_pass.Histo1D((
          'hist_pass_'+self.get_binname(ibin),
          ';'+self.fit_var_desc+';Events/bin',
          self.fit_var_nbins,
          self.fit_var_range[0],
          self.fit_var_range[1]),
          'tnpanalysis_fit_var',
          'tnpanalysis_fit_var_weight'))
      fail_hist_ptrs.append(df_bin_fail.Histo1D((
          'hist_fail_'+self.get_binname(ibin),
          ';'+self.fit_var_desc+';Events/bin',
          self.fit_var_nbins,
          self.fit_var_range[0],
          self.fit_var_range[1]),
          'tnpanalysis_fit_var',
          'tnpanalysis_fit_var_weight'))
    print('Performing event loop. This may take a while.')
    for ibin in range(0,self.nbins):
      pass_hist_ptrs[ibin].Write()
      fail_hist_ptrs[ibin].Write()

  def fit_histogram(self, ibin_str, pass_probe, model, param_initializer=''):
    '''
    Performs interactive fit to data

    ibin_str           string, bin to fit
    pass_probe         string, pass or fail
    model              string, model name
    param_initializer  string, parameter initializer name
    '''

    #do initial checks
    ibin = 0
    try:
      ibin = int(ibin_str)
    except ValueError:
      print('ERROR: Unable to cast bin, skipping fit.')
      return
    if ibin<0 or ibin>=self.nbins:
      print('ERROR: Bin out of range.')
      return
    if pass_probe not in ['pass','p','P','fail','f','F']:
      print('ERROR: <pass> parameter must be (p)ass or (f)ail.')
      return
    pass_bool = False
    pass_fail = 'fail'
    if pass_probe in ['pass','p','P']:
      pass_bool = True
      pass_fail = 'pass'
    if not model in self.model_initializers:
      print('ERROR: unknown fit model, aborting fit.')
      return
    if not param_initializer in self.param_initializers:
      if not param_initializer=='':
        print('ERROR: unknown param initializer, aborting fit.')
        return
    hist_name = 'hist_'+pass_fail+'_'+self.get_binname(ibin)
    if not self.temp_file.GetListOfKeys().Contains(hist_name):
      print('ERROR: Please produce histograms before calling fit.')
      return

    #initialize workspace
    fit_var = ROOT.RooRealVar('fit_var', self.fit_var_name, 
                              self.fit_var_range[0], self.fit_var_range[1]) 
    workspace = self.model_initializers[model](fit_var, ibin, pass_bool)
    data = ROOT.RooDataHist('data','fit variable', ROOT.RooArgList(fit_var), 
                            self.temp_file.Get(hist_name))
    getattr(workspace,'import')(data)
    if not param_initializer=='':
      self.param_initializers[param_initializer](ibin, pass_bool, workspace)

    #run interactive fit
    exit_loop = False
    fit_status = 0
    canvas = ROOT.TCanvas()
    data = workspace.data('data')
    pdf_sb = workspace.pdf('pdf_sb')
    param_names = workspace_vars_to_list(workspace)
    param_names.remove('fit_var')
    while not exit_loop:
      user_input = input('>:')
      user_input = user_input.split()
      if len(user_input)<1:
        continue
      elif user_input[0]=='list' or user_input[0]=='l':
        workspace_vars = workspace_vars_to_list(workspace)
        for param_name in workspace_vars:
          print(param_name+': '+str(workspace.var(param_name).getValV()))
        #workspace.Print('v') 
      elif user_input[0]=='help' or user_input[0]=='h':
        print('This is an interactive fitting session. Commands include:')
        print('f(it)                    attempt a fit')
        print('l(ist)                   display values of variables')
        print('c(onstant) <var> <value> set a value to constant or not')
        print('n(ext)                   finish fit and proceed to next bin')
        print('q(uit)                   exit interactive fitting session')
        print('q(uit)!                  exit session without saving result')
        print('j(son) <s/l> <fname>     saves or loads parameters to JSON file')
        print('r(evert)                 revert to prefit parameter values')
        print('s(et) <var> <value>      set variable <var> to <value>')
        print('w(rite) <fname>          write current canvas to a file')
      elif user_input[0]=='constant' or user_input[0]=='c':
        if len(user_input)<3:
          print('ERROR: (c)onstant takes two arguments: set <var> <value>')
          continue
        if not (user_input[1] in param_names):
          print('ERROR: unknown parameter '+user_input[1])
          continue
        constant_value = True
        if (user_input[2] == 'False' or user_input[2] == 'false'
            or user_input[2] == 'F' or user_input[2] == 'f'):
          constant_value = False
        workspace.var(user_input[1]).setConstant(constant_value)
      elif user_input[0]=='set' or user_input[0]=='s':
        if len(user_input)<3:
          print('ERROR: (s)et takes two arguments: set <var> <value>')
          continue
        if not (user_input[1] in param_names):
          print('ERROR: unknown parameter '+user_input[1])
          continue
        try:
          float(user_input[2])
          workspace.var(user_input[1]).setVal(float(user_input[2]))
          self.make_simple_tnp_plot(workspace, canvas)
        except ValueError:
          print('ERROR: Unable to cast value, skipping input.')
      elif user_input[0]=='json' or user_input[0]=='j':
        if len(user_input)<3:
          print('ERROR: (j)son takes two arguments: json <s/l> <fname>')
          continue
        if not user_input[1] in ['s','save','l','load','S','L']:
          print('ERROR: (j)son second argument must be (s)ave or (l)oad')
          continue
        is_save = (user_input[1] in ['s','save','S'])
        filename = user_input[2] 
        if (not is_save) and (not os.path.exists(filename)):
          print('ERROR: File not found.')
          continue
        if is_save and os.path.exists(filename):
          print('WARNING: file already exists, enter "y" to overwrite')
          user_input_2 = input()
          if user_input_2 != 'y':
            print('Aborting write.')
            continue
        if (is_save):
          param_dict = dict()
          for param_name in param_names:
            param_dict[param_name] = workspace.var(param_name).getValV()
          with open(filename,'w') as output_file:
            output_file.write(json.dumps(param_dict))
        if (not is_save):
          with open(filename,'r') as input_file:
            param_dict = json.loads(input_file.read())
            for param_name in param_dict:
              workspace.var(param_name).setVal(param_dict[param_name])
          self.make_simple_tnp_plot(workspace, canvas)
      elif user_input[0]=='fit' or user_input[0]=='f':
        workspace.saveSnapshot('prefit',','.join(param_names))
        fit_result_ptr = pdf_sb.fitTo(data,ROOT.RooFit.Save(True))
        fit_status = fit_result_ptr.status()
        ROOT.free_memory_RooFitResult(fit_result_ptr)
        print('Fit status: '+str(fit_status))
        self.make_simple_tnp_plot(workspace, canvas)
      elif user_input[0]=='revert' or user_input[0]=='r':
        workspace.loadSnapshot('prefit')
        self.make_simple_tnp_plot(workspace, canvas)
      elif user_input[0]=='write' or user_input[0]=='w':
        if len(user_input)<3:
          print('ERROR: (w)rite takes one argument: write <fname>')
          continue
        canvas.SaveAs(user_input[1])
      elif user_input[0]=='quit!' or user_input[0]=='q!':
        exit_loop = True
      elif (user_input[0]=='quit' or user_input[0]=='q' or user_input[0]=='n' or
           user_input[0]=='next'):
        #originally was going to save Workspace, but ROOT is too unstable, so
        #just saving fit parameter info to recreate later
        filename = ('out/'+self.temp_name+'/fitinfo_bin'+str(ibin)+'_'
                    +pass_fail+'.json')
        if os.path.exists(filename):
          print('WARNING: output file already exists, enter "y" to overwrite')
          user_input_2 = input()
          if user_input_2 != 'y':
            print('Aborting write.')
            continue
        param_dict = dict()
        for param_name in param_names:
          param_dict[param_name] = workspace.var(param_name).getValV()
          param_dict[param_name+'_unc'] = workspace.var(param_name).getError()
        param_dict['fit_status'] = fit_status
        param_dict['fit_model'] = model
        with open(filename,'w') as output_file:
          output_file.write(json.dumps(param_dict))
        if user_input[0]=='n' or user_input[0]=='next':
          if (ibin != self.nbins-1):
            self.fit_histogram(str(ibin+1), pass_probe, model, 
                               param_initializer)
          else:
            print('Exiting interactive fitter.')
        else:
          print('Exiting interactive fitter.')
        exit_loop = True

  def draw_fit_set(self, ibin, canvas):
    '''
    Draws fits and writes fit parameters. Writes to the current gPad (global 
    ROOT pad pointer) and returns a tuple (effificiency, uncertainty) for the
    current bin

    ibin    int, bin to analyze
    canvas  TCanvas on which to draw plots. Should be divided into ibins*3
    '''

    #draw fit to passing leg on middle subpad
    canvas.cd(ibin*3+2)
    ROOT.gPad.SetMargin(0.1,0.1,0.1,0.1)
    pass_param_dict = dict()
    param_filename = 'out/'+self.temp_name+'/fitinfo_bin'+str(ibin)+'_pass.json'
    hist_name = 'hist_pass_'+self.get_binname(ibin)
    with open(param_filename,'r') as input_file:
      pass_param_dict = json.loads(input_file.read())
    fit_var_pass = ROOT.RooRealVar('fit_var', self.fit_var_name, 
                              self.fit_var_range[0], self.fit_var_range[1]) 
    pass_workspace = self.model_initializers[pass_param_dict['fit_model']](fit_var_pass, ibin, True)
    data_pass = ROOT.RooDataHist('data','fit variable', ROOT.RooArgList(fit_var_pass), 
                            self.temp_file.Get(hist_name))
    getattr(pass_workspace,'import')(data_pass)
    for param_name in pass_param_dict:
      if ((not (param_name == 'fit_model' or param_name == 'fit_status')) and
          (not '_unc' in param_name)):
        pass_workspace.var(param_name).setVal(pass_param_dict[param_name])
    pass_plot = pass_workspace.var('fit_var').frame()
    pass_workspace.data('data').plotOn(pass_plot)
    pass_workspace.pdf('pdf_sb').plotOn(pass_plot,ROOT.RooFit.Name('fit_sb'))
    sig_norm_temp = pass_workspace.var('nSig').getValV()
    bak_norm_temp = pass_workspace.var('nBkg').getValV()
    pass_workspace.var('nSig').setVal(0.0)
    pass_workspace.pdf('pdf_sb').plotOn(pass_plot,
        ROOT.RooFit.Normalization(bak_norm_temp/(sig_norm_temp+bak_norm_temp),
        ROOT.RooAbsReal.Relative),ROOT.RooFit.Name('fit_b'))
    pass_workspace.var('nSig').setVal(sig_norm_temp)
    pass_plot.Draw()
    ROOT.gPad.Update()

    #draw fit to failing leg on right subpad
    canvas.cd(ibin*3+3)
    ROOT.gPad.SetMargin(0.1,0.1,0.1,0.1)
    fail_param_dict = dict()
    param_filename = 'out/'+self.temp_name+'/fitinfo_bin'+str(ibin)+'_fail.json'
    hist_name = 'hist_fail_'+self.get_binname(ibin)
    with open(param_filename,'r') as input_file:
      fail_param_dict = json.loads(input_file.read())
    fit_var_fail = ROOT.RooRealVar('fit_var', self.fit_var_name, 
                              self.fit_var_range[0], self.fit_var_range[1]) 
    fail_workspace = self.model_initializers[fail_param_dict['fit_model']](fit_var_fail, ibin, False)
    data_fail = ROOT.RooDataHist('data','fit variable', ROOT.RooArgList(fit_var_fail), 
                            self.temp_file.Get(hist_name))
    getattr(fail_workspace,'import')(data_fail)
    for param_name in fail_param_dict:
      if ((not (param_name == 'fit_model' or param_name == 'fit_status')) and
          (not '_unc' in param_name)):
        fail_workspace.var(param_name).setVal(fail_param_dict[param_name])
    fail_plot = fail_workspace.var('fit_var').frame()
    fail_workspace.data('data').plotOn(fail_plot)
    fail_workspace.pdf('pdf_sb').plotOn(fail_plot,ROOT.RooFit.Name('fit_sb'))
    sig_norm_temp = fail_workspace.var('nSig').getValV()
    bak_norm_temp = fail_workspace.var('nBkg').getValV()
    fail_workspace.var('nSig').setVal(0.0)
    fail_workspace.pdf('pdf_sb').plotOn(fail_plot,
        ROOT.RooFit.Normalization(bak_norm_temp/(sig_norm_temp+bak_norm_temp),
        ROOT.RooAbsReal.Relative),ROOT.RooFit.Name('fit_b'))
    fail_workspace.var('nSig').setVal(sig_norm_temp)
    fail_plot.Draw()
    ROOT.gPad.Update()

    #write text on left subpad
    canvas.cd(ibin*3+1)
    nsig_pass = pass_param_dict['nSig']
    nsig_fail = fail_param_dict['nSig']
    nsig_pass_unc = pass_param_dict['nSig_unc']
    nsig_fail_unc = fail_param_dict['nSig_unc']
    nsig_total = nsig_pass+nsig_fail
    nsig_total_unc = math.hypot(nsig_pass_unc, nsig_fail_unc)
    eff = 0.0
    unc = 1.0
    if (nsig_pass > 0.0):
      eff = nsig_pass/nsig_total
      unc = eff*math.hypot(nsig_pass_unc/nsig_pass, nsig_total_unc/nsig_total)
    else:
      print('WARNING: no fit passing signal in bin '+str(ibin))
    pad_text = self.bin_names[ibin]+'\n'
    pad_text += ('Fit status pass: {}\n'.format(pass_param_dict['fit_status']))
    pad_text += ('Fit status fail: {}\n'.format(fail_param_dict['fit_status']))
    pad_text += ('Efficiency: {:.4f} #pm {:.4f}\n'.format(eff,unc))
    pad_text += 'Fit parameters:\n'
    for param_name in pass_param_dict:
      if ((not (param_name == 'fit_model' or param_name == 'fit_status')) and
          (not '_unc' in param_name)):
        pad_text += ('{}P = {:.4f} #pm {:.4f}\n'.format(
            param_name, pass_param_dict[param_name], pass_param_dict[param_name+'_unc']))
    for param_name in fail_param_dict:
      if ((not (param_name == 'fit_model' or param_name == 'fit_status')) and
          (not '_unc' in param_name)):
        pad_text += ('{}F = {:.4f} #pm {:.4f}\n'.format(
            param_name, fail_param_dict[param_name], fail_param_dict[param_name+'_unc']))
    latex = ROOT.TLatex()
    latex.SetTextSize(0.03)
    write_multiline_latex(0.1,0.9,latex,pad_text)

    return (eff, unc)

  def generate_final_output(self):
    '''
    Generates plots of all the fits and a text file with the measured efficiencies and uncertainties
    '''
    #do checks
    plot_filename = 'out/'+self.temp_name+'/allfits.pdf'
    effi_filename = 'out/'+self.temp_name+'/efficiencies.json'
    if os.path.exists(plot_filename) or os.path.exists(effi_filename):
      print('ERROR: output files already exist')
      return
    file_keys = self.temp_file.GetListOfKeys()
    for ibin in range(0,self.nbins):
      for pass_fail in ('pass','fail'):
        param_filename = ('out/'+self.temp_name+'/fitinfo_bin'+str(ibin)+
                          '_'+pass_fail+'.json')
        if not os.path.exists(param_filename):
          print('ERROR:'+param_filename+' not found.')
          return

    #draw final plots and calculate final efficiencies
    #each pass/fail/parameters pad is 426 x 240, with 1.02 x padding 435 x 245
    nbins_x = self.nbins_x
    nbins_y = self.nbins//nbins_x
    #x_margin = 0.02*(nbins_x*435)
    #y_margin = 0.02*(nbins_y*245)
    x_margin = 0.00
    y_margin = 0.00
    canvas = ROOT.TCanvas('output_canvas','',nbins_x*1200,nbins_y*480)
    canvas.Divide(nbins_x*3, nbins_y, x_margin, y_margin)
    effs = []
    for ibin in range(0,self.nbins):
      effs.append(self.draw_fit_set(ibin,canvas))
    canvas.SaveAs(plot_filename)
    with open(effi_filename,'w') as output_file:
      output_file.write(json.dumps(effs))
    print('Wrote '+effi_filename)

  def print_info(self):
    '''
    Prints basic information about T&P Analyzer
    '''
    print('Number of bin: '+str(self.nbins))
    print('Available models: ')
    for model in self.model_initializers:
      print('  '+model)
    print('Available parameter initializers: ')
    for param in self.param_initializers:
      print('  '+param)

  def run_interactive(self):
    '''
    Begin interactive run
    '''

    self.check_initialization()
    self.initialize_files_directories()

    #run main interactive loop
    exit_loop = False
    print('Welcome to tnp_tools interactive analysis. Type [h]elp for more information.')
    while not exit_loop:
      user_input = input('>:')
      user_input = user_input.split()
      if len(user_input)<1:
        continue
      elif (user_input[0] == 'h' or user_input[0] == 'help'):
        print('Available commands:')
        print('p(roduce)                                  produce histograms to fit')
        print('f(it) <bin> <pass> <model> [<initializer>] perform interactive fit to histograms')
        print('i(nfo)                                     list info about available bins/models/initializers')
        print('h(elp)                                     print help information')
        print('o(utput)                                   generate final output from fits (not yet implemented)')
        print('q(uit)                                     exit the interactive session')
      elif (user_input[0] == 'p' or user_input[0] == 'produce'):
        self.produce_histograms()
      elif (user_input[0] == 'i' or user_input[0] == 'info'):
        self.print_info()
      elif (user_input[0] == 'f' or user_input[0] == 'fit'):
        print('Beginning interactive fitting session.')
        if len(user_input)>=5:
          self.fit_histogram(user_input[1],user_input[2],user_input[3],user_input[4])
        elif len(user_input)==4:
          self.fit_histogram(user_input[1],user_input[2],user_input[3])
        else:
          print('ERROR: (f)it requires at least 3 arguments')
      elif (user_input[0] == 'o' or user_input[0] == 'output'):
        self.generate_final_output()
      elif (user_input[0] == 'q' or user_input[0] == 'quit'):
        print('Exiting interactive session and saving temp file')
        exit_loop = True
        self.temp_file.Close()



