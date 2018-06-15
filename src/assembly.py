'''
Linearise UVLM assembly
S. Maraniello, 25 May 2018

Includes:

- Boundary conditions methods:
	- AICs: allocate aero influence coefficient matrices of multi-surfaces 
	configurations
	- nc_dqcdzeta_Sin_to_Sout: derivative matrix of
		nc*dQ/dzeta 
	where Q is the induced velocity at the bound colllocation points of one 
	surface to another
	- nc_dqcdzeta_coll: assembles "nc_dqcdzeta_coll_Sin_to_Sout" matrices in 
	multi-surfaces configurations
	- uc_dncdzeta: assemble derivative matrix dnc/dzeta*Uc at bound collocation 
	points

'''

import numpy as np

import libder.uc_dncdzeta
import libder.dbiot

from IPython import embed



# local indiced panel/vertices as per self.maps
dmver=[ 0, 1, 1, 0] # delta to go from (m,n) panel to (m,n) vertices
dnver=[ 0, 0, 1, 1]
svec =[ 0, 1, 2, 3] # seg. no.
avec =[ 0, 1, 2, 3] # 1st vertex no.
bvec =[ 1, 2, 3, 0] # 2nd vertex no.


def skew(Av):
	''' Produce skew matrix such that Av x Bv = skew(Av)*Bv	'''	

	ax,ay,az=Av[0],Av[1],Av[2]
	Askew=np.array([[  0,-az, ay],
					[ az,  0,-ax],
					[-ay, ax,  0] ])

	return Askew



def AICs(Surfs,Surfs_star,target='collocation',Project=True):
	'''
	Given a list of bound (Surfs) and wake (Surfs_star) instances of 
	surface.AeroGridSurface, returns the list of AIC matrices in the format:
	 	- AIC_list[ii][jj] contains the AIC from the bound surface Surfs[jj] to 
	 	Surfs[ii].
	 	- AIC_star_list[ii][jj] contains the AIC from the wake surface Surfs[jj] 
	 	to Surfs[ii].
	'''

	AIC_list=[]
	AIC_star_list=[]

	n_surf=len(Surfs)
	assert len(Surfs_star)==n_surf,\
							   'Number of bound and wake surfaces much be equal'

	for ss_out in range(n_surf):
		AIC_list_here=[]
		AIC_star_list_here=[]
		Surf_out=Surfs[ss_out]

		for ss_in in range(n_surf):
			# Bound surface
			Surf_in=Surfs[ss_in]
			AIC_list_here.append(Surf_in.get_aic_over_surface(
										Surf_out,target=target,Project=Project))
			# Wakes
			Surf_in=Surfs_star[ss_in]
			AIC_star_list_here.append(Surf_in.get_aic_over_surface(
										Surf_out,target=target,Project=Project))
		AIC_list.append(AIC_list_here)
		AIC_star_list.append(AIC_star_list_here)	

	return AIC_list, AIC_star_list




def nc_dqcdzeta_Sin_to_Sout(Surf_in,Surf_out,Der_coll,Der_vert,Surf_in_bound):
	'''
	Computes derivative matrix of
		nc*dQ/dzeta
	where Q is the induced velocity induced by bound surface Surf_in onto 
	bound surface Surf_out. The panel normals of Surf_out are constant.

	The input/output are:
	- Der_coll of size (Kout,3*Kzeta_out): derivative due to the movement of 
	collocation point on Surf_out. 
	- Der_vert of size:
		- (Kout,3*Kzeta_in) if Surf_in_bound is True
		- (Kout,3*Kzeta_bound_in) if Surf_in_bound is False; Kzeta_bound_in is 
		the number of vertices in the bound surface of whom Surf_out is the wake.

	Note that:
	- if Surf_in_bound is False, only the TE movement contributes to Der_vert.
	- if Surf_in_bound is False, the allocation of Der_coll could be speed-up by
	scanning only the wake segments along the chordwise direction, as on the 
	others the net circulation is null.
	'''

	# calc collocation points (and weights)
	if not hasattr(Surf_out,'zetac'):
		Surf_out.generate_collocations()
	ZetaColl=Surf_out.zetac
	wcv_out=Surf_out.get_panel_wcv()

	# extract sizes / check matrices
	K_out=Surf_out.maps.K
	Kzeta_out=Surf_out.maps.Kzeta
	K_in=Surf_in.maps.K
	Kzeta_in=Surf_in.maps.Kzeta

	assert Der_coll.shape==(K_out,3*Kzeta_out) , 'Unexpected Der_coll shape'
	if Surf_in_bound:
		assert Der_vert.shape==(K_out,3*Kzeta_in) , 'Unexpected Der_vert shape'
	else:
		# determine size of bound surface of which Surf_in is the wake
		Kzeta_bound_in=Der_vert.shape[1]//3
		N_in=Surf_in.maps.N
		M_bound_in=Kzeta_bound_in//(N_in+1)-1
		shape_bound_in=(M_bound_in+1,N_in+1)

	# create mapping panels to vertices to loop 
	Surf_out.maps.map_panels_to_vertices_1D_scalar()
	Surf_in.maps.map_panels_to_vertices_1D_scalar()

	##### loop collocation points
	for cc_out in range(K_out):

		# get (m,n) indices of collocation point
		mm_out=Surf_out.maps.ind_2d_pan_scal[0][cc_out]
		nn_out=Surf_out.maps.ind_2d_pan_scal[1][cc_out]
		# get coords and normal
		zetac_here=ZetaColl[:,mm_out,nn_out]
		nc_here=Surf_out.normals[:,mm_out,nn_out]
		# get indices of panel vertices
		gl_ind_panel_out=Surf_out.maps.Mpv1d_scalar[cc_out]

		######  loop panels input surface 
		for pp_in in range(K_in):
			# get (m,n) indices of panel
			mm_in=Surf_in.maps.ind_2d_pan_scal[0][pp_in]
			nn_in=Surf_in.maps.ind_2d_pan_scal[1][pp_in]	
			# get vertices coords and circulation			
			zeta_panel=Surf_in.get_panel_vertices_coords(mm_in,nn_in)
			gamma_panel=Surf_in.gamma[mm_in,nn_in]

			# get local derivatives
			der_zetac,der_zeta_panel=libder.dbiot.eval_panel(
								    zetac_here,zeta_panel,gamma_pan=gamma_panel)
			

			##### Allocate collocation point contribution
			der_zetac_proj=np.dot(nc_here,der_zetac)
			for vv in range(4):
				gl_ind_vv=gl_ind_panel_out[vv]
				for vv_comp in range(3):
					Der_coll[cc_out,gl_ind_vv+vv_comp*Kzeta_out]+=\
										 wcv_out[vv]*der_zetac_proj[vv_comp]


			##### Allocate panel vertices contributions

			### Bound wake case
			if Surf_in_bound is True:
				# get global indices of panel vertices
				gl_ind_panel_in=Surf_in.maps.Mpv1d_scalar[pp_in]
				for vv in range(4):
					gl_ind_vv=gl_ind_panel_in[vv]
					for vv_comp in range(3):
						Der_vert[cc_out,gl_ind_vv+vv_comp*Kzeta_in]+=\
									np.dot(nc_here,der_zeta_panel[vv,vv_comp,:])

			### Allocate TE vertices contributions only					
			else: 
				if mm_in==0:				
					der_zeta_seg=libder.dbiot.eval_seg(zetac_here,
						  zeta_panel[3,:],zeta_panel[0,:],gamma_seg=gamma_panel)

					# Define indices of vertices 0 and 3 on bound surface
					mm0,mm3=M_bound_in,M_bound_in
					nn0,nn3=nn_in,nn_in+1
					gl_ind0=np.ravel_multi_index( [mm0,nn0],\
									             dims=shape_bound_in, order='C')
					gl_ind3=np.ravel_multi_index( [mm3,nn3],\
									             dims=shape_bound_in, order='C')

					# allocate
					for vv_comp in range(3):
						Der_vert[cc_out,gl_ind3+vv_comp*Kzeta_bound_in]+=\
									   np.dot(nc_here,der_zeta_seg[1,vv_comp,:])
						Der_vert[cc_out,gl_ind0+vv_comp*Kzeta_bound_in]+=\
									   np.dot(nc_here,der_zeta_seg[2,vv_comp,:])	

	return Der_coll, Der_vert




def nc_dqcdzeta(Surfs,Surfs_star):
	'''
	Produces a list of derivative matrix d(AIC*Gamma)/dzeta, where AIC are the 
	influence coefficient matrices at the bound surfaces collocation point, 
	ASSUMING constant panel norm.

	Eeach list is such that:
	- the ii-th element is associated to the ii-th bound surface collocation
	point, and will contain a sub-list such that:
		- the j-th element of the sub-list is the dAIC_dzeta matrices w.r.t. the 
		zeta d.o.f. of the j-th bound surface. 
	Hence, DAIC*[ii][jj] will have size K_ii x Kzeta_jj
	'''

	n_surf=len(Surfs)
	assert len(Surfs_star)==n_surf,\
							   'Number of bound and wake surfaces much be equal'

	DAICcoll=[]
	DAICvert=[]

	### loop output (bound) surfaces
	for ss_out in range(n_surf):

		# define output bound surface size
		Surf_out=Surfs[ss_out]
		K_out=Surf_out.maps.K
		Kzeta_out=Surf_out.maps.Kzeta

		# derivatives w.r.t collocation points: all the in surface scanned will
		# manipulate this matrix, as the collocation points are on Surf_out
		Dcoll=np.zeros((K_out,3*Kzeta_out))
		# derivatives w.r.t. panel coordinates will affect dof on bound Surf_in
		# (not wakes)
		DAICvert_sub=[]

		# loop input surfaces:
		for ss_in in range(n_surf):
			
			##### bound
			Surf_in=Surfs[ss_in]
			Kzeta_in=Surf_in.maps.Kzeta

			# compute terms
			Dvert=np.zeros((K_out,3*Kzeta_in))
			Dcoll,Dvert=nc_dqcdzeta_Sin_to_Sout(
							    Surf_in,Surf_out,Dcoll,Dvert,Surf_in_bound=True)

			##### wake:
			Surf_in=Surfs_star[ss_in]
			Dcoll,Dvert=nc_dqcdzeta_Sin_to_Sout(
							   Surf_in,Surf_out,Dcoll,Dvert,Surf_in_bound=False)
			DAICvert_sub.append(Dvert)

		DAICcoll.append(Dcoll)
		DAICvert.append(DAICvert_sub)

	return 	DAICcoll, DAICvert


################################################################################



def uc_dncdzeta(Surf):
	'''
	Build derivative of uc*dnc/dzeta where uc is the total velocity at the
	collocation points. Input Surf can be:
	- an instance of surface.AeroGridSurface.
	- a list of instance of surface.AeroGridSurface. 	
	Refs:
	- develop_sym.linsum_Wnc
	- libder.uc_dncdzeta
	'''

	if type(Surf) is list:
		n_surf=len(Surf)
		DerList=[]
		for ss in range(n_surf):
			DerList.append(uc_dncdzeta(Surf[ss]))
		return DerList
	else:
		if (not hasattr(Surf,'u_ind_coll')) or (not hasattr(Surf,'u_input_coll')):
			raise NameError(
			'Surf does not have the required attributes\nu_ind_coll\nu_input_coll')

	Map=Surf.maps
	K,Kzeta=Map.K,Map.Kzeta
	Der=np.zeros((K,3*Kzeta))

	# map panel to vertice
	if not hasattr(Map.Mpv,'Mpv1d_scalar'):
		Map.map_panels_to_vertices_1D_scalar()
	if not hasattr(Map.Mpv,'Mpv'):
		Map.map_panels_to_vertices()

	# map u_normal 2d to 1d
	# map_panels_1d_to_2d=np.unravel_index(range(K),
	# 						   				  dims=Map.shape_pan_scal,order='C')
	# for ii in range(K):

	for ii in Map.ind_1d_pan_scal:

		# panel m,n coordinates
		m_pan,n_pan=Map.ind_2d_pan_scal[0][ii],Map.ind_2d_pan_scal[1][ii]
		# extract u_input_coll
		u_tot_coll_here=\
				 Surf.u_input_coll[:,m_pan,n_pan]+Surf.u_ind_coll[:,m_pan,n_pan]

		# find vertices
		mpv=Map.Mpv[m_pan,n_pan,:,:]

		# extract m,n coordinates of vertices
		zeta00=Surf.zeta[:,mpv[0,0],mpv[0,1]]
		zeta01=Surf.zeta[:,mpv[1,0],mpv[1,1]]
		zeta02=Surf.zeta[:,mpv[2,0],mpv[2,1]]
		zeta03=Surf.zeta[:,mpv[3,0],mpv[3,1]]

		# calculate derivative
		Dlocal=libder.uc_dncdzeta.eval(zeta00,zeta01,zeta02,zeta03,
															    u_tot_coll_here)

		for vv in range(4):
			# find 1D position of vertices
			jj=Map.Mpv1d_scalar[ii,vv]

			# allocate derivatives
			Der[ii,jj]=Dlocal[vv,0] # w.r.t. x
			Der[ii,jj+Kzeta]=Dlocal[vv,1] # w.r.t. y
			Der[ii,jj+2*Kzeta]=Dlocal[vv,2] # w.r.t. z

	return Der




def dfqsdgamma_vrel(Surfs,Surfs_star):
	'''
	Assemble derivative of quasi-steady force w.r.t. gamma with fixed relative
	velocity - the changes in induced velocities due to gamma are not accounted
	for. The routine exploits the get_joukovski_qs method insude the 
	AeroGridSurface class
	'''

	
	Der_list=[]
	Der_star_list=[]

	n_surf=len(Surfs)
	assert len(Surfs_star)==n_surf,\
							   'Number of bound and wake surfaces much be equal'

	for ss in range(n_surf):

		Surf=Surfs[ss]
		if not hasattr(Surf,'u_ind_seg'):
			raise NameError('Induced velocities at segments missing')
		if not hasattr(Surf,'u_input_seg'):
			raise NameError('Input velocities at segments missing')
		if not hasattr(Surf,'fqs_seg'):
			Surf.get_joukovski_qs(gammaw_TE=Surfs_star[ss].gamma[0,:])

		M,N=Surf.maps.M,Surf.maps.N
		K=Surf.maps.K
		Kzeta=Surf.maps.Kzeta
		shape_fqs=Surf.maps.shape_vert_vect # (3,M+1,N+1)

		##### unit gamma contribution of BOUND panels
		Der=np.zeros((3*Kzeta,K))

		# loop panels (input, i.e. matrix columns)
		for pp_in in range(K):
			# get (m,n) indices of panel
			mm_in=Surf.maps.ind_2d_pan_scal[0][pp_in]
			nn_in=Surf.maps.ind_2d_pan_scal[1][pp_in]	

			# zetav_here=Surf.get_panel_vertices_coords(mm_in,nn_in)
			for ll,aa,bb in zip(svec,avec,bvec):
				# import libuvlm 
				# dfhere=libuvlm.joukovski_qs_segment(
				# 	zetaA=zetav_here[aa,:],zetaB=zetav_here[bb,:],
				# 	v_mid=Surf.u_ind_seg[:,ll,mm_in,nn_in]+\
				# 		  Surf.u_input_seg[:,ll,mm_in,nn_in],
				# 	gamma=1.0,fact=0.5*Surf.rho)
				df=(0.5/Surf.gamma[mm_in,nn_in])*Surf.fqs_seg[:,ll,mm_in,nn_in]
				# assert np.abs(np.max(dfhere-df))<1e-13,'something is wrong'

				# get vertices m,n indices
				mm_a,nn_a=mm_in+dmver[aa],nn_in+dnver[aa]
				mm_b,nn_b=mm_in+dmver[bb],nn_in+dnver[bb]

				# get vertices 1d index
				ii_a=[ np.ravel_multi_index( 
								  (cc,mm_a,nn_a),shape_fqs ) for cc in range(3)]
				ii_b=[ np.ravel_multi_index( 
								  (cc,mm_b,nn_b),shape_fqs ) for cc in range(3)]
				Der[ii_a,pp_in]+=df
				Der[ii_b,pp_in]+=df

		Der_list.append(Der)


		##### unit gamma contribution of WAKE TE segments
		# Note: the force due to the wake is attached to Surf when 
		# get_joukovski_qs is acalled
		M_star,N_star=Surfs_star[ss].maps.M,Surfs_star[ss].maps.N
		K_star=Surfs_star[ss].maps.K
		shape_in=Surfs_star[ss].maps.shape_pan_scal # (M_star,N_star)

		Der_star=np.zeros((3*Kzeta,K_star))

		assert N==N_star,\
					  'trying to associate wrong wake to current bound surface!'

		# loop bound panels
		for nn_in in range(N):
			pp_in=np.ravel_multi_index( (0,nn_in),shape_in)

			df=(0.5/Surfs_star[ss].gamma[0,nn_in])*Surf.fqs_wTE[:,nn_in]

			# get TE bound vertices m,n indices
			mm_a,nn_a=M,nn_in+dnver[aa]
			mm_b,nn_b=M,nn_in+dnver[bb]

			# get vertices 1d index
			ii_a=[ np.ravel_multi_index( 
								  (cc,mm_a,nn_a),shape_fqs ) for cc in range(3)]
			ii_b=[ np.ravel_multi_index( 
								  (cc,mm_b,nn_b),shape_fqs ) for cc in range(3)]
			Der_star[ii_a,pp_in]+=df
			Der_star[ii_b,pp_in]+=df

		Der_star_list.append(Der_star)

	return Der_list, Der_star_list




def dfqsdzeta_vrel(Surfs,Surfs_star):
	'''
	Assemble derivative of quasi-steady force w.r.t. zeta with fixed relative
	velocity - the changes in induced velocities due to zeta over the surface
	inducing the velocity are not accounted for. The routine exploits the 
	available relative velocities at the mid-segment points
	'''

	Der_list=[]
	n_surf=len(Surfs)
	assert len(Surfs_star)==n_surf,\
							   'Number of bound and wake surfaces much be equal'

	for ss in range(n_surf):

		Surf=Surfs[ss]
		if not hasattr(Surf,'u_ind_seg'):
			raise NameError('Induced velocities at segments missing')
		if not hasattr(Surf,'u_input_seg'):
			raise NameError('Input velocities at segments missing')

		M,N=Surf.maps.M,Surf.maps.N
		K=Surf.maps.K
		Kzeta=Surf.maps.Kzeta
		shape_fqs=Surf.maps.shape_vert_vect # (3,M+1,N+1)

		##### unit gamma contribution of BOUND panels
		Der=np.zeros((3*Kzeta,3*Kzeta))

		# loop panels (input, i.e. matrix columns)
		for pp_in in range(K):
			# get (m,n) indices of panel
			mm_in=Surf.maps.ind_2d_pan_scal[0][pp_in]
			nn_in=Surf.maps.ind_2d_pan_scal[1][pp_in]	

			for ll,aa,bb in zip(svec,avec,bvec):

				vrel_seg=(Surf.u_input_seg[:,ll,mm_in,nn_in]+
					          				   Surf.u_ind_seg[:,ll,mm_in,nn_in])
				Df=skew( (0.5*Surf.rho*Surf.gamma[mm_in,nn_in])*vrel_seg )

				# get vertices m,n indices
				mm_a,nn_a=mm_in+dmver[aa],nn_in+dnver[aa]
				mm_b,nn_b=mm_in+dmver[bb],nn_in+dnver[bb]

				# get vertices 1d index
				ii_a=[ np.ravel_multi_index( 
								  (cc,mm_a,nn_a),shape_fqs ) for cc in range(3)]
				ii_b=[ np.ravel_multi_index( 
								  (cc,mm_b,nn_b),shape_fqs ) for cc in range(3)]
				# Der[ii_a,:][:,ii_a]+=-Df
				# Der[ii_b,:][:,ii_b]+=Df
				Der[np.ix_(ii_a,ii_a)]+=-Df
				Der[np.ix_(ii_b,ii_a)]+=-Df
				Der[np.ix_(ii_a,ii_b)]+=Df
				Der[np.ix_(ii_b,ii_b)]+=Df

		##### contribution of WAKE TE segments.
		# This is added to Der, as only the bound vertices are included in the 
		# input

		# loop TE bound segment but:
		# - using wake gamma
		# - using orientation of wake panel
		for nn_in in range(N):
			# get velocity at seg.3 of wake TE
			vrel_seg=(Surf.u_input_seg[:,1,M-1,nn_in]+Surf.u_ind_seg[:,1,M-1,nn_in])
			Df=Df=skew( 
				(0.5*Surfs_star[ss].rho*Surfs_star[ss].gamma[0,nn_in])*vrel_seg)

			# get TE bound vertices m,n indices
			nn_a=nn_in+dnver[2]
			nn_b=nn_in+dnver[1]
			# get vertices 1d index on bound
			ii_a=[ np.ravel_multi_index( 
									 (cc,M,nn_a),shape_fqs ) for cc in range(3)]
			ii_b=[ np.ravel_multi_index( 
									 (cc,M,nn_b),shape_fqs ) for cc in range(3)]

			Der[np.ix_(ii_a,ii_a)]+=-Df
			Der[np.ix_(ii_b,ii_a)]+=-Df
			Der[np.ix_(ii_a,ii_b)]+=Df
			Der[np.ix_(ii_b,ii_b)]+=Df
		Der_list.append(Der)

	return Der_list






# -----------------------------------------------------------------------------

if __name__=='__main__':
	pass 