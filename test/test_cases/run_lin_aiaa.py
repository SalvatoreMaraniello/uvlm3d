'''
Modified Goland wing static analysis parametric study:
- rigid structure with change in input speed
'''
import time
import copy
import numpy as np
import scipy as sc
import scipy.signal as scsig
import sys, os
import warnings
# from IPython import embed
import matplotlib.pyplot as plt 
# sharpy
sys.path.append("/home/ng213/code/sharpy/")
import sharpy.sharpy_main
import sharpy.utils.solver_interface as solver_interface
import sharpy.solvers.modal as modal
import sharpy.utils.h5utils as h5
import cases.templates.flying_wings as flying_wings
# linear uvlm
os.environ["DIRuvlm3d"] = "/home/ng213/linuvlm/uvlm3d/src/"
sys.path.append( os.environ["DIRuvlm3d"] )
import save, linuvlm, lin_aeroelastic, libss, librom
import pp_plot as pp
plt.rcParams.update(pp.std_params)


def comp_tot_force( forces,zeta,zeta_pole=np.zeros((3,)) ):
	''' Compute total force with exact displacements '''
	Ftot=np.zeros((3,))
	Mtot=np.zeros((3,))
	for ss in range(len(forces)):
		_,Mv,Nv=forces[ss].shape
		for mm in range(Mv):
			for nn in range(Nv):
				arm=zeta[ss][:,mm,nn]-zeta_pole
				Mtot+=np.cross(arm,forces[ss][:3,mm,nn])
		for cc in range(3):
			Ftot[cc]+=forces[ss][cc,:,:].sum()
	return Ftot,Mtot


class Info():
	''' Summarise info about a data point '''
	def __init__(self,zeta,zeta_dot,u_ext,ftot,mtot,q,qdot,
					  SSaero=None,SSbeam=None,
				      Kas=None,Kftot=None,Kmtot=None,Kmtot_disp=None,
				      										  Asteady_inv=None):
		self.zeta=zeta 
		self.zeta_dot=zeta_dot 
		self.u_ext=u_ext 
		self.ftot=ftot 
		self.mtot=mtot 
		self.q=q 
		self.qdot=qdot
		#
		self.SSaero=SSaero
		self.SSbeam=SSbeam
		self.Kas=Kas
		self.Kftot=Kftot
		self.Kmtot=Kmtot
		self.Kmtot_disp=Kmtot_disp
		self.Asteady_inv=Asteady_inv


def solve_linear(Ref,Pert,solve_beam=True):
	'''
	Given 2 Info classes associated to a reference linearisation point Ref and a
	perturbed state Pert, the method produces in output the prediction at the 
	Pert state of a linearised model.

	The solution is carried on using both the aero and beam input
	'''

	### define perturbations
	dq=Pert.q-Ref.q
	dqdot=Pert.qdot-Ref.qdot
	dzeta=Pert.zeta-Ref.zeta
	dzeta_dot=Pert.zeta_dot-Ref.zeta_dot
	du_ext=Pert.u_ext-Ref.u_ext

	num_dof_str=len(dq)
	dzeta_exp=np.dot(Ref.Kas[:len(dzeta),:num_dof_str] ,dq)

	SSaero=Ref.SSaero 
	SSbeam=Ref.SSbeam

	# zeta in
	usta=np.concatenate([dzeta,dzeta_dot,du_ext])
	if hasattr(Ref,'Asteady_inv'):
		xsta=np.dot( Ref.Asteady_inv, np.dot(SSaero.B,usta) )
	else:
		Asteady=np.eye(*SSaero.A.shape)-SSaero.A
		xsta=np.linalg.solve( Asteady, np.dot(SSaero.B,usta) )
	ysta=np.dot(SSaero.C,xsta)+np.dot(SSaero.D,usta)
	ftot_aero=Ref.ftot+np.dot(Ref.Kftot,ysta)
	mtot_aero=Ref.mtot+np.dot(Ref.Kmtot,ysta)+np.dot(Ref.Kmtot_disp,dzeta)	

	
	#### beam in
	if solve_beam:
		# warning: we need to add first the contribution due to velocity change!!!
		usta_uinf=np.concatenate([0.*dzeta,0.*dzeta_dot,du_ext])
		xsta_uinf=np.linalg.solve( Asteady, np.dot(SSaero.B,usta_uinf) )
		ysta_uinf=np.dot(SSaero.C,xsta_uinf)+np.dot(SSaero.D,usta_uinf)
		usta=np.concatenate([dq,dqdot])
		if hasattr(Ref,'Asteady_inv'):
			xsta=np.dot( Ref.Asteady_inv, np.dot(SSbeam.B,usta) )
		else:
			Asteady=np.eye(*SSbeam.A.shape)-SSbeam.A
			xsta=np.linalg.solve( Asteady, np.dot(SSbeam.B,usta) )
		ysta=ysta_uinf+np.dot(SSbeam.C,xsta)+np.dot(SSbeam.D,usta)
		ftot_beam=Ref.ftot+np.dot(Ref.Kftot,ysta)
		mtot_beam=Ref.mtot+np.dot(Ref.Kmtot,ysta)+np.dot(Ref.Kmtot_disp,dzeta_exp)	
	else:
		ftot_beam,mtot_beam=None,None

	return ftot_aero,mtot_aero,ftot_beam,mtot_beam



def extract_from_data(data,assemble=True,
							 zeta_pole=np.zeros((3,)),build_Asteady_inv=False ):
	'''
	Extract relevant info from data structure. If assemble is True, it will 
	also generate a linear UVLM and the displacements/velocities gain matrices
	'''

	### extract aero info
	tsaero=data.aero.timestep_info[0]
	zeta=np.concatenate([tsaero.zeta[ss].reshape(-1,order='C') 
											    for ss in range(tsaero.n_surf)])
	zeta_dot=np.concatenate([tsaero.zeta_dot[ss].reshape(-1,order='C') 
											    for ss in range(tsaero.n_surf)])
	uext=np.concatenate([tsaero.u_ext[ss].reshape(-1,order='C') 
											    for ss in range(tsaero.n_surf)])
	ftot,mtot=comp_tot_force(tsaero.forces,tsaero.zeta,zeta_pole=zeta_pole)

	## TEST WHETHER SETTINGS RUN
	settings = dict()
	settings['LinearUvlm'] = {'dt': 0.1,
							  'integr_order':2,
							  'density': 1.225,
							  'ScalingDict':{'length': 1. ,
											 'speed': 1. ,
											 'density':1.}}

	### extract structural info
	Sol=lin_aeroelastic.LinAeroEla(data, settings)
	gebm=Sol.lingebm_str
	q=Sol.q
	qdot=Sol.dq

	### assemble
	if assemble is True:
		uvlm=Sol.linuvlm
		uvlm.assemble_ss()
		uvlm.get_total_forces_gain(zeta_pole=zeta_pole)
		Sol.get_gebm2uvlm_gains()
		Kas=np.block([[Sol.Kdisp    , np.zeros((3*uvlm.Kzeta,gebm.num_dof+10))],
					  [Sol.Kvel_disp, Sol.Kvel_vel 						   	  ],
					  [np.zeros((3*uvlm.Kzeta,2*gebm.num_dof+20))             ]])
		SSbeam=libss.addGain(uvlm.SS, Kas, where='in')

		if build_Asteady_inv:
			Asteady_inv=np.linalg.inv( np.eye(*uvlm.SS.A.shape)-uvlm.SS.A )
		else:
			Asteady_inv=None
		Out=Info(zeta,zeta_dot,uext,ftot,mtot,q,qdot,
		 			uvlm.SS,SSbeam,Kas,uvlm.Kftot,uvlm.Kmtot,uvlm.Kmtot_disp,
		 															Asteady_inv)

	else:
		Out=Info(zeta,zeta_dot,uext,ftot,mtot,q,qdot)

	return Out


# -----------------------------------------------------------------------------


# Define Parametrisation
M,N,Mstar_fact= 20,40,20 # HF (flex/rig)
# M,N,Mstar_fact=4, 40, 20 # LF (flex/rig)

Rigid=1#True
# linearisation point
PPlist=[2,8]
#PPlist=[5,25]



Nsurf=1
u_inf=150.
ZetaPole=np.zeros((3,))

# Flying properties
pvec=np.linspace(-1,1,11)
# pvec=np.linspace(-1,1,31)


AlphaFoRA=0.0
SideMidDeg=0.
SideMaxDeg=6.0
AlphaInfMid=0.
AlphaInfMax=3.
AlphaInfVecDeg=AlphaInfMid+AlphaInfMax*pvec
AlphaVecDeg=0.*pvec+AlphaFoRA
SideVecDeg=SideMidDeg+SideMaxDeg*pvec
RollVecDeg=0.*pvec
Npoints=len(AlphaVecDeg)


if Rigid:
	figsfold='./figs/rigid_aiaa/'
	route_main=os.path.abspath('.') + '/cases/rigid/'
	case_main='goland_mod_rig_Nsurf%.2dM%.2dN%.2dwk%.2d' %(Nsurf,M,N,Mstar_fact)
else:
	figsfold='./figs/flex_aiaa/'
	route_main=os.path.abspath('.') + '/cases/flex/'
	case_main='goland_mod_flex_Nsurf%.2dM%.2dN%.2dwk%.2d' %(Nsurf,M,N,Mstar_fact)
os.system('mkdir -p %s'%figsfold)


# ------------------------------------------------ extract linearisation points
Nlin=len(PPlist)

print('Linearisation points [deg]')
print('ainf\tarig\tside_rig')
for ll in range(Nlin):
	PP=PPlist[ll]
	tplparams=( AlphaInfVecDeg[PP], AlphaVecDeg[PP], SideVecDeg[PP] ) 
	print(3*'%.3f\t'%tplparams[:3])


Refs=[]
for ll in range(Nlin):
	PP=PPlist[ll]
	tplparams=(int(np.round(100*AlphaInfVecDeg[PP])),
				int(np.round(100*AlphaVecDeg[PP])),
			   int(np.round(100*SideVecDeg[PP])) ,
			   int(np.round(100*RollVecDeg[PP])) )
	case_here=case_main+'_ainf%.4da%.4ds%.4dr%.4d'%tplparams 
	route_here=route_main

	data0=h5.readh5(route_here+case_here+'.data.h5').data
	Refs.append( extract_from_data(data0,assemble=True,
								     zeta_pole=ZetaPole,build_Asteady_inv=True))



# ---------------------------------------------------------- loop through cases

Dzeta_max=np.zeros((Nlin,Npoints))

# reference forces from exct analysis
Fref=np.zeros((Npoints,3))
Mref=np.zeros((Npoints,3))

# linearised total forces
Faero=np.zeros((Nlin,Npoints,3))
Maero=np.zeros((Nlin,Npoints,3))


for nn in range(Npoints):

	### update parameters
	tplparams=(int(np.round(100*AlphaInfVecDeg[nn])),
				int(np.round(100*AlphaVecDeg[nn])),
			   int(np.round(100*SideVecDeg[nn])) ,
			   int(np.round(100*RollVecDeg[nn])) )
	case_here=case_main+'_ainf%.4da%.4ds%.4dr%.4d'%tplparams 
	route_here=route_main

	data=h5.readh5(route_here+case_here+'.data.h5').data
	Pert=extract_from_data(data,assemble=False,zeta_pole=ZetaPole)

	# reference
	Fref[nn,:]=Pert.ftot
	Mref[nn,:]=Pert.mtot

	# linear
	for ll in range(Nlin):
		Faero[ll,nn,:],Maero[ll,nn,:],fb,mb=solve_linear(Refs[ll],Pert,solve_beam=False)



### ----------------------------------------------------------------------------


### total forces
rho=np.float(data0.settings['LinearUvlm']['density'])
qinf=0.5*rho*u_inf**2
chord=1.8288
span=2.*6.096
Sref=span*chord
Fsc=qinf*Sref
Msc=Fsc*chord


clab=['x','y','z']
clist=[pp.cdict['royal-blue'],'k',pp.cdict['orange']]
llist=['--',':','-.']
wlist=[5,5,5]
clab=['x','y','z']
if Rigid:
	savename='goland_mod_rigid_Nsurf%.2dM%.2dN%.2dwk%.2d'%(Nsurf,M,N,Mstar_fact)
else:
	savename='goland_mod_flex_Nsurf%.2dM%.2dN%.2dwk%.2d'%(Nsurf,M,N,Mstar_fact)


hleg=[]
labs=[]
# pv=np.linspace(-1,1,Npoints)
plt.close('all')
for cc in range(3):

	fig = plt.figure('Total force comp. %.1d'%cc ,(10,5))
	ax=fig.add_subplot(111)
	axup = ax.twiny()

	# geometrically-exact
	labs.append( r'geometrically-exact' )
	hleg.append(ax.plot( AlphaInfVecDeg,Fref[:,cc]/Fsc,
						  lw=5,ls='-',alpha=0.7,color=pp.cdict['clear-red'])[0])
	# linear (aero dof)
	for ll in range(Nlin):
		PP=PPlist[ll]
		labs.append(r'linear ($\alpha_\infty=%.1f$ deg, $\gamma=%.1f$ deg)'\
										   %(AlphaInfVecDeg[PP],SideVecDeg[PP]))
		hleg.append( 
			ax.plot( AlphaInfVecDeg,Faero[ll,:,cc]/Fsc,
						lw=wlist[ll],ls=llist[ll],alpha=0.7,color=clist[ll],)[0])
	ax.grid(color='0.8', ls='-')
	ax.grid(color='0.85', ls='-', which='minor')
	ax.set_xlabel(r'$\alpha_\infty$ [deg]')
	ax.set_xlim(AlphaInfVecDeg[0],AlphaInfVecDeg[-1])
	ax.set_ylabel(r'$C_{F_%s}$'%clab[cc])

	axup.set_xlim( SideVecDeg[0],SideVecDeg[1] )
	upticks=2*ax.get_xticks()
	axup.set_xticks( upticks )
	axup.set_xticklabels( ['%.0f'%tt for tt in upticks ] )
	axup.set_xlabel(r'$\gamma$ [deg]')

	# ax.legend()
	fig.savefig(figsfold+'/%sftot_comp%.2d.png'%(savename,cc))
	fig.savefig(figsfold+'/%sftot_comp%.2d.pdf'%(savename,cc))	


### build legend - horiz
figleg=plt.figure('Legend',(12,1))
figleg.legend(hleg[:1+Nlin],labs[:1+Nlin],ncol=4,loc='center',frameon=False,columnspacing=2,labelspacing=.4)
figleg.savefig(figsfold+'/legend.png')
figleg.savefig(figsfold+'/legend.pdf')	


figleg=plt.figure('Legend vert',(6,3))
figleg.legend(hleg[:1+Nlin],labs[:1+Nlin],ncol=1,loc='center',frameon=False,columnspacing=2,labelspacing=.4)
figleg.savefig(figsfold+'/legend_vert.png')
figleg.savefig(figsfold+'/legend_vert.pdf')	





plt.show()
plt.close('all')

### save output
class OutData():
	name='plot'
	pass
out=OutData()
out.Fsc=Fsc
out.Msc=Msc
out.Faero=Faero
out.Maero=Maero
out.Fref=Fref
out.Fref=Fref
out.AlphaInfVecDeg=AlphaInfVecDeg
out.SideVecDeg=SideVecDeg
save.h5file(figsfold,savename+'.h5',*(out,))




