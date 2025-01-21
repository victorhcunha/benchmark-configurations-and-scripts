require "open3"

class TestCase
	attr_reader :command, :benchmark_path, :test_case_path

	def initialize(benchmark_path, test_case_path)
		@benchmark_path = benchmark_path
		@test_case_path = test_case_path
		@command = "ant reload-warmup-database all-portal start-visualvm all-grinder all-sample stop -Dskip.build.portal=true"
	end

	def run_case
		copy_files
		run_command(@command, @benchmark_path)
	end

	private
	def copy_files
		print ">> Copy files from [#@test_case_path] to [bundle-configs].\n\n"
		run_command("cp -f /#@test_case_path/benchmark-ext.properties ./", @benchmark_path)
	end

	private
	def read_from_file(path_to_file)
		buffer = ""
		File.open(path_to_file, "r") do |file|
			buffer = file.read
		end
		buffer
	end

	private
	def write_to_file(path_to_file, content)
		File.open(path_to_file, "w") do |file|
			file.write(content)
		end
	end
end

class Login < TestCase
end

class MessageBoard < TestCase
	def run_case
		copy_files
		run_command("ant reload-warmup-database all-portal start-visualvm all-grinder all-sample stop -Dskip.build.portal=true", @benchmark_path)
	end
end

class WebContent < Login
end

class ObjectDefinition < Login
end

class ContentPage < Login
end

class AssetPublisher < Login
end

class DocumentLibrary < MessageBoard
end

class Commerce < Login
end

class Blog < MessageBoard
end

class Wiki < MessageBoard
end

class WikiIndex < MessageBoard
end

class PrintHandler
	def handle(str)
		print "\t#{str}"
	end
end

class SaveHandler
	def initialize()
		@result = ""
	end

	def handle(str)
		@result += str
	end

	def get_result
		@result
	end
end

def get_case(test_case, benchmark_path, test_case_path)
	if test_case.include? "login"
		Login.new(benchmark_path, test_case_path)
	elsif test_case.include? "wc"
		WebContent.new(benchmark_path, test_case_path)
	elsif test_case.include? "object"
		ObjectDefinition.new(benchmark_path, test_case_path)
	elsif test_case.include? "fragment"
		ContentPage.new(benchmark_path, test_case_path)
	elsif test_case.include? "mb"
		MessageBoard.new(benchmark_path, test_case_path)
	elsif test_case.include? "dl"
		DocumentLibrary.new(benchmark_path, test_case_path)
	elsif test_case.include? "blog"
		Blog.new(benchmark_path, test_case_path)
	elsif test_case.include? "wiki"
		Wiki.new(benchmark_path, test_case_path)
	elsif test_case.include? "wiki_index"
		WikiIndex.new(benchmark_path, test_case_path)
	elsif test_case.include? "assetpublisher"
		AssetPublisher.new(benchmark_path, test_case_path)
	elsif test_case.include? "commerce"
		Commerce.new(benchmark_path, test_case_path)
	end
end

def run_command(command, path, handler = PrintHandler.new)
	_, stdout_err, t = nil

	Dir.chdir path do
		_, stdout_err, t = Open3.popen2e({"LANGUAGE" => "en_US"}, command)
	end

	stdout_err.each do |stream|
		handler.handle stream
	end

	exit_code = t.value.to_i

	unless exit_code == 0
		sleep 0.1
		abort "Failed to execute [#{command}]."
	end
end

def main_test_process
	test_case_category = ARGV[0]
	test_cases = ARGV[1].split ","

	benchmark_path = "/home/liferay/dev/projects/liferay-benchmark-ee/"
	test_case_root_path = "/home/liferay/dev/projects/benchmark-configurations-and-scripts/#{test_case_category}"

	# build grinder
	#print ">> Build Grinder before running test...\n"
	#run_command("ant clean jar", "#{benchmark_path}/grinder", PrintHandler.new)

	# run tests: testcase level
	test_cases.each do |test_case|
		test_case_path = "#{test_case_root_path}/#{test_case}"
		run_command("ant stop", benchmark_path)
		print "\n\n\n\n\n>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>"
		print "\n\n>> Starting [#{test_case}] test."
		test_case = get_case(test_case, benchmark_path, test_case_path)
		print "\n\n>> Run: #{test_case.command}\n\n"
		test_case.run_case
		print "\n\n>> Finished [#{test_case}] test.\n\n\n\n"
	end
end

if __FILE__ == $0
	abort abort_message if ARGV.empty?

	main_test_process
end
