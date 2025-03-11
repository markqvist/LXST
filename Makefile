all: release

clean:
	@echo Cleaning...
	-rm -r ./build
	-rm -r ./dist

remove_symlinks:
	@echo Removing symlinks for build...
	-rm ./RNS
	-rm ./LXST/Utilities/LXST
	-rm ./examples/LXST

create_symlinks:
	@echo Creating symlinks...
	-ln -s ../Reticulum/RNS ./
	-ln -s ../../LXST/ ./LXST/Utilities/LXST
	-ln -s ../LXST/ ./examples/LXST

build_wheel:
	python3 setup.py sdist bdist_wheel

release: remove_symlinks build_wheel create_symlinks

upload:
	@echo Ready to publish release, hit enter to continue
	@read VOID
	@echo Uploading to PyPi...
	twine upload dist/*
	@echo Release published
