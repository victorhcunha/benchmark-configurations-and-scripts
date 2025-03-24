public class ObjectEntriesGenerator {
	public static void main(String[] args) throws IOException {
		int size = 2000000;

		try (BufferedWriter bufferedWriter = Files.newBufferedWriter(Paths.get("~/generated.json"), StandardOpenOption.CREATE, StandardOpenOption.WRITE, StandardOpenOption.TRUNCATE_EXISTING)) {
			bufferedWriter.write("[\n");

			for (int i = 0; i < size; i++) {
				bufferedWriter.write("{\"alpha\" : \"VOO\"}");

				if (i < size - 1) {
					bufferedWriter.write(",\n");
				}
			}
			bufferedWriter.write("\n]");
		}
	}
}