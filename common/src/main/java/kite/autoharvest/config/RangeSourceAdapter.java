package kite.autoharvest.config;

import com.google.gson.TypeAdapter;
import com.google.gson.stream.JsonReader;
import com.google.gson.stream.JsonToken;
import com.google.gson.stream.JsonWriter;

import java.io.IOException;

/** Reads the old enum setting while always saving the new boolean toggle. */
public final class RangeSourceAdapter extends TypeAdapter<Boolean> {
    @Override
    public Boolean read(JsonReader reader) throws IOException {
        if (reader.peek() == JsonToken.BOOLEAN) {
            return reader.nextBoolean();
        }
        if (reader.peek() == JsonToken.STRING) {
            String value = reader.nextString();
            return "PLAYER_ATTRIBUTE".equals(value) || Boolean.parseBoolean(value);
        }
        // Unexpected values retain the custom-radius default without resetting other settings.
        reader.skipValue();
        return false;
    }

    @Override
    public void write(JsonWriter writer, Boolean value) throws IOException {
        writer.value(Boolean.TRUE.equals(value));
    }
}
